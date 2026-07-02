"""Signature detection: a YOLOv8s ONNX model run as a pure-vision post-pass.

NOTE: the weights (``tech4humans/yolov8s-signature-detector``, a fine-tuned Ultralytics
YOLOv8s) are licensed AGPL-3.0. That obligation lives in the weights themselves — using
``onnxruntime`` instead of the ``ultralytics`` package avoids AGPL on library *code* but
NOT on the weights. Accepted for this internal/demo build; get licensing sign-off before
any external/SaaS distribution.

This module is storage/schema-AGNOSTIC: it turns a page PNG into pixel-space
:class:`Detection` boxes and nothing more. ``onnxruntime`` + ``huggingface_hub`` are
lazily imported and the session is a cached singleton, so the app boots and structuring
runs without the optional ``signatures`` extra or the model file present — an
unresolvable model raises :class:`SignatureDetectorUnavailable`, which the structuring
post-pass swallows into a warning.

The decode is the standard YOLOv8 detection export: letterbox to 640, single output
``[1,5,8400]`` = ``(cx,cy,w,h,conf)`` per anchor (anchor-free, no objectness), threshold
by confidence, cxcywh->xyxy, NMS, then un-letterbox back to original page pixels.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.config import settings

logger = logging.getLogger(__name__)

_SESSION = None  # cached onnxruntime InferenceSession across requests


@dataclass
class Detection:
    """One detected signature: a pixel-space box + its confidence."""

    bbox: tuple[float, float, float, float]  # x0,y0,x1,y1 in original page-pixel space
    confidence: float


class SignatureDetectorUnavailable(RuntimeError):
    """Raised when the detector can't run: optional deps missing or model unresolvable."""


def _resolve_model_path() -> Path:
    """Locate the ONNX weights: local path first, optional HF_TOKEN download fallback.

    Never hard-requires ``huggingface_hub``: the download branch is only attempted when
    the local file is absent AND an ``HF_TOKEN`` is set in the environment. Raises
    :class:`SignatureDetectorUnavailable` when the weights can't be resolved.
    """
    local = settings.signature_model_full_path
    if local.exists():
        return local

    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SignatureDetectorUnavailable(
            f"signature model not found at {local} and HF_TOKEN is not set"
        )
    try:
        from huggingface_hub import hf_hub_download  # lazy: optional dep
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise SignatureDetectorUnavailable(
            "huggingface_hub is not installed (install the 'signatures' extra)"
        ) from exc
    try:
        downloaded = hf_hub_download(
            repo_id=settings.signature_model_repo,
            filename=settings.signature_model_file,
            token=token,
        )
    except Exception as exc:  # noqa: BLE001 - network/gating failures degrade gracefully
        raise SignatureDetectorUnavailable(
            f"could not download signature model from {settings.signature_model_repo}: {exc}"
        ) from exc
    return Path(downloaded)


def _session():
    """Lazily create (and cache) the onnxruntime session for the signature model.

    Raises :class:`SignatureDetectorUnavailable` if ``onnxruntime`` is not installed or
    the weights can't be resolved — callers swallow that into a best-effort warning.
    """
    global _SESSION
    if _SESSION is None:
        try:
            import onnxruntime as ort  # lazy: optional dep
        except ImportError as exc:
            raise SignatureDetectorUnavailable(
                "onnxruntime is not installed (install the 'signatures' extra)"
            ) from exc
        model_path = _resolve_model_path()
        _SESSION = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
    return _SESSION


def _letterbox(
    image_rgb: np.ndarray, size: int, color: tuple[int, int, int] = (114, 114, 114)
) -> tuple[np.ndarray, float, int, int]:
    """Aspect-preserving resize + centered gray pad to ``size``x``size``.

    Returns ``(canvas, r, pad_w, pad_h)`` where ``r`` is the scale factor and
    ``(pad_w, pad_h)`` the left/top pad — the exact quantities needed to un-letterbox
    detections back to the original pixel space.
    """
    h, w = image_rgb.shape[:2]
    r = min(size / h, size / w)
    nw, nh = round(w * r), round(h * r)
    resized = cv2.resize(image_rgb, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), color, dtype=np.uint8)
    pad_w, pad_h = (size - nw) // 2, (size - nh) // 2
    canvas[pad_h:pad_h + nh, pad_w:pad_w + nw] = resized
    return canvas, r, pad_w, pad_h


def _preprocess(bgr: np.ndarray) -> tuple[np.ndarray, float, int, int]:
    """BGR page -> ``([1,3,640,640]`` float32 RGB/255, r, pad_w, pad_h)."""
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    lb, r, pad_w, pad_h = _letterbox(rgb, settings.signature_input_size)
    x = lb.astype(np.float32) / 255.0
    x = np.transpose(x, (2, 0, 1))[None]  # HWC -> CHW, add batch
    return np.ascontiguousarray(x), r, pad_w, pad_h


def _postprocess(
    raw: np.ndarray,
    r: float,
    pad_w: int,
    pad_h: int,
    orig_w: int,
    orig_h: int,
) -> list[Detection]:
    """Decode a ``[1,5,8400]`` YOLOv8 output into pixel-space :class:`Detection`.

    Thresholds by confidence, converts cxcywh->xyxy, runs NMS, then un-letterboxes
    (``(coord - pad) / r``) and clips to the page bounds. Thresholds come from settings.
    """
    conf_thres = settings.signature_conf_threshold
    iou_thres = settings.signature_iou_threshold

    preds = np.squeeze(np.asarray(raw), 0).T  # [8400,5] -> (cx,cy,w,h,score)
    scores = preds[:, 4]
    keep = scores >= conf_thres
    preds, scores = preds[keep], scores[keep]
    if preds.shape[0] == 0:
        return []

    cx, cy, w, h = preds[:, 0], preds[:, 1], preds[:, 2], preds[:, 3]
    x1 = cx - w / 2
    y1 = cy - h / 2

    # cv2.dnn.NMSBoxes wants [x, y, w, h] boxes (in the 640-letterboxed space).
    boxes_xywh = np.stack([x1, y1, w, h], axis=1).tolist()
    idxs = cv2.dnn.NMSBoxes(boxes_xywh, scores.tolist(), conf_thres, iou_thres)
    if len(idxs) == 0:
        return []
    idxs = np.array(idxs).flatten()

    x2 = cx + w / 2
    y2 = cy + h / 2
    # Un-letterbox: subtract pad, divide by scale -> original page pixels.
    bx1 = (x1[idxs] - pad_w) / r
    by1 = (y1[idxs] - pad_h) / r
    bx2 = (x2[idxs] - pad_w) / r
    by2 = (y2[idxs] - pad_h) / r
    boxes = np.stack([bx1, by1, bx2, by2], axis=1)
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, orig_w)
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, orig_h)

    return [
        Detection(bbox=(float(b[0]), float(b[1]), float(b[2]), float(b[3])), confidence=float(s))
        for b, s in zip(boxes, scores[idxs])
    ]


def detect_signatures(page_path: Path) -> list[Detection]:
    """Detect signatures on one page PNG, returning pixel-space boxes.

    Raises :class:`SignatureDetectorUnavailable` when the session can't load (missing
    deps / model). A per-page decode failure (unreadable image, bad output) returns ``[]``
    rather than raising, so one bad page never aborts the whole post-pass.
    """
    session = _session()
    try:
        bgr = cv2.imread(str(page_path))
        if bgr is None:
            logger.warning("signature detector could not read page image %s", page_path)
            return []
        x, r, pad_w, pad_h = _preprocess(bgr)
        input_name = session.get_inputs()[0].name
        raw = session.run(None, {input_name: x})[0]
        h, w = bgr.shape[:2]
        return _postprocess(raw, r, pad_w, pad_h, w, h)
    except Exception as exc:  # noqa: BLE001 - a per-page decode failure is non-fatal
        logger.warning("signature detection failed on %s: %s", page_path, exc)
        return []


def crop_signature(image: Image.Image, bbox, padding_px: int) -> Image.Image:
    """Crop ``bbox`` (x0,y0,x1,y1) out of ``image``, padded and clamped to its bounds."""
    x0, y0, x1, y1 = bbox
    w, h = image.size
    left = max(0, int(round(x0)) - padding_px)
    top = max(0, int(round(y0)) - padding_px)
    right = min(w, int(round(x1)) + padding_px)
    bottom = min(h, int(round(y1)) + padding_px)
    # Guard against an inverted/degenerate box producing an empty crop.
    if right <= left:
        right = min(w, left + 1)
    if bottom <= top:
        bottom = min(h, top + 1)
    return image.crop((left, top, right, bottom))


def warm() -> None:
    """Force-load the session so the first real detection call isn't cold.

    Best-effort: :class:`SignatureDetectorUnavailable` (no deps / no model) propagates to
    the caller, which logs it as a warning rather than failing.
    """
    _session()

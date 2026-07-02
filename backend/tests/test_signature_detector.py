"""Unit tests for the pure-vision signature detector.

Exercise the letterbox / decode / crop math offline: the ONNX session is monkeypatched
to return a synthetic ``[1,5,8400]`` output, so no real weights are loaded and nothing
hits the network (mirrors how the OCR tests stub the VLM client).
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from app.pipeline import signature_detector as sd
from app.pipeline.signature_detector import Detection, SignatureDetectorUnavailable


class _FakeInput:
    name = "images"


class _FakeSession:
    """Stand-in ONNX session returning a fixed raw output regardless of the input."""

    def __init__(self, raw: np.ndarray) -> None:
        self._raw = raw

    def get_inputs(self):
        return [_FakeInput()]

    def run(self, output_names, feed):  # noqa: ARG002 - signature mirrors onnxruntime
        return [self._raw]


def _raw_with(anchors: list[list[float]]) -> np.ndarray:
    """A ``[1,5,8400]`` output with ``anchors`` (cx,cy,w,h,score) filling the first slots."""
    raw = np.zeros((1, 5, 8400), dtype=np.float32)
    for i, a in enumerate(anchors):
        raw[0, :, i] = a
    return raw


def test_letterbox_scale_pad_and_shape():
    # 200x100 image, letterbox to 640: r = min(640/100, 640/200) = 3.2, width fills, pad top/bottom.
    img = np.zeros((100, 200, 3), dtype=np.uint8)
    canvas, r, pad_w, pad_h = sd._letterbox(img, 640)
    assert canvas.shape == (640, 640, 3)
    assert r == pytest.approx(3.2)
    assert pad_w == 0
    assert pad_h == 160
    # The pad region carries the gray fill color.
    assert list(canvas[0, 0]) == [114, 114, 114]


def test_postprocess_unletterboxes_to_original_pixels():
    # Intended original box (40,60,140,160) at r=0.5, pad=(20,10) -> letterbox cxcywh.
    raw = _raw_with([[65.0, 65.0, 50.0, 50.0, 0.9]])
    dets = sd._postprocess(raw, r=0.5, pad_w=20, pad_h=10, orig_w=400, orig_h=300)
    assert len(dets) == 1
    x0, y0, x1, y1 = dets[0].bbox
    assert (x0, y0, x1, y1) == pytest.approx((40.0, 60.0, 140.0, 160.0))
    assert dets[0].confidence == pytest.approx(0.9)


def test_postprocess_confidence_threshold_filters():
    # One box above the 0.45 default, one below -> only the strong one survives.
    raw = _raw_with([[65.0, 65.0, 50.0, 50.0, 0.9], [300.0, 300.0, 40.0, 40.0, 0.10]])
    dets = sd._postprocess(raw, r=1.0, pad_w=0, pad_h=0, orig_w=640, orig_h=640)
    assert len(dets) == 1
    assert dets[0].confidence == pytest.approx(0.9)


def test_postprocess_nms_dedups_overlapping_boxes():
    # Two heavily-overlapping high-conf boxes -> NMS keeps the higher-scoring one.
    raw = _raw_with([[100.0, 100.0, 60.0, 60.0, 0.9], [102.0, 101.0, 60.0, 60.0, 0.85]])
    dets = sd._postprocess(raw, r=1.0, pad_w=0, pad_h=0, orig_w=640, orig_h=640)
    assert len(dets) == 1
    assert dets[0].confidence == pytest.approx(0.9)


def test_postprocess_empty_when_all_below_threshold():
    raw = _raw_with([[100.0, 100.0, 60.0, 60.0, 0.05]])
    assert sd._postprocess(raw, r=1.0, pad_w=0, pad_h=0, orig_w=640, orig_h=640) == []


def test_crop_signature_pads_and_clamps():
    img = Image.new("RGB", (100, 100), "white")
    # Interior box: padded by 5 on every side.
    crop = sd.crop_signature(img, (10, 10, 50, 50), padding_px=5)
    assert crop.size == (50, 50)
    # Box overflowing the bottom-right: clamps to the image bounds.
    clamped = sd.crop_signature(img, (90, 90, 200, 200), padding_px=5)
    assert clamped.size == (15, 15)
    # Degenerate (zero-area) box: never produces an empty crop.
    degenerate = sd.crop_signature(img, (50, 50, 50, 50), padding_px=0)
    assert degenerate.size == (1, 1)


def test_detect_signatures_end_to_end_with_stub_session(monkeypatch, tmp_path):
    # A 640x640 page => r=1, no pad, so letterbox coords equal original pixels.
    page = tmp_path / "page.png"
    Image.new("RGB", (640, 640), "white").save(page, "PNG")
    raw = _raw_with([[100.0, 100.0, 40.0, 40.0, 0.9]])
    monkeypatch.setattr(sd, "_session", lambda: _FakeSession(raw))

    dets = sd.detect_signatures(page)
    assert len(dets) == 1
    assert dets[0].bbox == pytest.approx((80.0, 80.0, 120.0, 120.0))
    assert dets[0].confidence == pytest.approx(0.9)


def test_detect_signatures_propagates_unavailable(monkeypatch, tmp_path):
    def _boom():
        raise SignatureDetectorUnavailable("no model")

    monkeypatch.setattr(sd, "_session", _boom)
    with pytest.raises(SignatureDetectorUnavailable):
        sd.detect_signatures(tmp_path / "missing.png")


def test_detect_signatures_unreadable_image_returns_empty(monkeypatch, tmp_path):
    # Session loads fine, but the file isn't a valid image -> non-fatal, returns [].
    monkeypatch.setattr(sd, "_session", lambda: _FakeSession(_raw_with([])))
    bogus = tmp_path / "not-an-image.png"
    bogus.write_bytes(b"not a png")
    assert sd.detect_signatures(bogus) == []


def test_detection_dataclass_shape():
    det = Detection(bbox=(1.0, 2.0, 3.0, 4.0), confidence=0.5)
    assert det.bbox == (1.0, 2.0, 3.0, 4.0)
    assert det.confidence == 0.5

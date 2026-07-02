# Signature extraction (Phase 1)

Located + cropped handwritten-signature detection, layered onto the existing
text-span-grounded extraction pipeline without disturbing it.

> Fits in the pipeline at [ARCHITECTURE.md §4c](./ARCHITECTURE.md#4c-signature-detection);
> the "is a signature present?" approval rule is [`signature_presence`](./validation-rules.md).
> For the feature pitch, see the [root README](../README.md#signature-detection).

## How it works

A YOLOv8s ONNX model (`tech4humans/yolov8s-signature-detector`, run via `onnxruntime` —
**not** the `ultralytics` package) runs as a **best-effort spatial post-pass** over the
rendered page PNGs, *inside* the structuring stage. It is gated by a doc type declaring a
field of the new `kind="signature"`.

Pipeline seam — `backend/app/pipeline/structuring.py`:

```
run_structuring
  → spec.assemble(flats, ctx)          # LLM/text extraction as before
  → _backfill_from_tables(...)
  → _detect_signatures(...)            # NEW: YOLO post-pass, only if spec.signature_fields
  → fields_model.model_dump()
  → _flatten_grounding(fields)         # signatures.N flatten into grounding_map for free
```

Each detection becomes one `FieldValue` in a top-level `signatures: list[FieldValue]`:

```json
{
  "value": true,
  "confidence": 0.91,
  "grounding": {
    "page": 2,
    "bbox": [412.0, 880.5, 610.2, 955.0],
    "image_url": "/files/<doc_id>/signatures/page-002-sig-01.png"
  }
}
```

`value=true` means "a signature was detected"; a reviewer can flip it to `false` to dismiss a
false positive, reusing the existing edit/correction machinery. `bbox` is `[x0,y0,x1,y1]`
top-left-origin in original page-pixel space (same convention as `OCRBlock.bbox`); the crop is
saved under `data/<doc_id>/signatures/` and served via `/files`.

## Why this shape

The pipeline is otherwise text-span-grounded (char offsets → snippet → OCR-block bbox). A
signature is an image region with little/no text, so it bypasses that path: the detector emits a
real pixel bbox directly, `Grounding` was extended with optional `bbox`/`image_url`, and the
frontend `rectsForField` gained a fast path that uses `grounding.bbox` verbatim (no OCR match
needed). `list[FieldValue]` is an existing renderable shape, so the structured panel, page overlay,
edit-in-place, and correction logging all work unchanged; `StructuredPanel.Leaf` just renders a
thumbnail when `grounding.image_url` is set. Both frontend hooks are generic (keyed on the bbox /
image_url, not the field name), so any future spatially-detected field (stamp, seal, logo) reuses
them.

## Configuration (`backend/app/config.py`)

| setting | default | purpose |
|---|---|---|
| `signature_detection_enabled` | `True` | master toggle for the post-pass |
| `signature_model_path` | `app/models/yolov8s.onnx` | local weights path (loaded first) |
| `signature_model_repo` / `signature_model_file` | `tech4humans/...` / `yolov8s.onnx` | HF fallback |
| `signature_conf_threshold` | `0.45` | detection confidence floor (calibrated — see Accuracy below) |
| `signature_iou_threshold` | `0.45` | NMS IoU |
| `signature_crop_padding_px` | `6` | padding added around each saved crop |

## Weights delivery

Loads from the local `signature_model_path` first. If absent and `HF_TOKEN` is set in the
environment, it falls back to `huggingface_hub.hf_hub_download` (the HF repo is **gated** — accept
its terms once and provide a token). If neither the optional deps (`onnxruntime`/`huggingface-hub`,
the `signatures` extra) nor the model file are available, the detector is a **graceful no-op**:
`signatures` stays `[]`, a warning is appended, and structuring succeeds normally. The app and all
existing tests run without any of this installed.

Install the optional stack with: `uv sync --extra signatures`.

## License note

The YOLOv8 weights are **AGPL-3.0** (inherited from the base model), independent of dropping the
`ultralytics` pip package. `onnxruntime` itself is MIT. AGPL is fine for internal/demo use, but its
§13 network-use clause should be reviewed before any external/SaaS distribution — consider a
friendlier-licensed detector (e.g. a DETR-based signature model) at that point.

## Accuracy & limitations (measured)

The detector was evaluated on a set of **real** documents (not composites) pulled from Wikimedia
Commons, plus the actual model swapped in (`nace-ai/yolov8s-signature-detection`, ungated, same
YOLOv8s architecture as the gated `tech4humans` original). Findings:

**Works reliably on the target domain** — typed/printed documents with a distinct handwritten
signature (the app's real input): a typed White House letter (0.84), a printed bank check (0.54),
a typed letter (0.81), and the composited contract (0.76/0.78) all detect correctly and box the
signature tightly. It also correctly returns **nothing** on a page with no signature.

**Known ceiling — out-of-domain documents fail** and no parameter tuning fixes it. This was
confirmed by sweeping input size (640→1536), confidence, IoU, and test-time augmentation, **and**
by testing a second architecture (`tech4humans/conditional-detr-50-signature-detector`):
- **Fully-handwritten pages** (e.g. a cursive letter): both models box body cursive instead of the
  actual signature — there's no typed context to disambiguate. Higher resolution makes this *worse*
  (more false boxes on the handwriting).
- **Aged / low-contrast historical forms**: signatures detect only weakly (below threshold) or not
  at all.
These are outside the training distribution (Tobacco800 — 20th-century typed business documents)
and are not representative of contract/invoice inputs.

**Threshold calibration.** On the real-document eval, genuine signatures scored **≥ 0.53** while
false positives (body cursive) scored **≤ 0.36**. The default `signature_conf_threshold` is set to
**0.45** — squarely in that gap — which keeps every true positive and drops the noise. The net
effect: clean precision (no false boxes on any tested document), at the cost of missing signatures
on the out-of-domain historical scans (the model can't find those regardless). Input size is kept
at the trained **640** (larger sizes regressed the wide-format check and inflated false positives).

If broad robustness on handwritten/degraded documents is ever required, that needs a different
model trained on that distribution — not a threshold change. The DETR variant was evaluated and is
**not** a net improvement (it missed the check and the deed and added a heavy `torch`/`transformers`
dependency), so YOLOv8s + onnxruntime remains the better fit here.

## Scope

Phase 1 ships on the **contract** doc type only (`extraction/contract.py`). Invoices have no
signature concept. Threshold calibration against real samples, a manual "add signature region"
affordance, and the alternative detector are follow-ups.


---

📚 **Docs:** [Index](./README.md) · [Architecture](./ARCHITECTURE.md) · [API](./API.md) · [Roadmap](./ROADMAP.md) · [Validation rules](./validation-rules.md) · [Large-doc extraction](./large-document-extraction.md) · **Signatures** · [Validation brainstorm](./VALIDATION-BRAINSTORM.md) · [↑ Root README](../README.md)

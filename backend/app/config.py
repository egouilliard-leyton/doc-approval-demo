"""Application settings, loaded from environment / .env file."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo path of the backend/ package, used to resolve relative storage paths.
BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Env-driven configuration for the document approval backend."""

    # OpenRouter agent (used from Phase 5 onward).
    openrouter_api_key: str = ""
    openrouter_model: str = "deepseek/deepseek-v4-flash"

    # Where uploaded files + the SQLite DB live (relative to backend/).
    data_dir: str = "data"

    # Ingestion settings (Phase 1).
    render_dpi: int = 200  # rasterize PDF pages to PNG at this DPI.
    thumbnail_width: int = 400  # max thumbnail width in px.
    max_upload_mb: int = 25

    # Pre-flight thresholds (Phase 2). Advisory/warn-only; the authoritative
    # needs_review verdict comes from OCR confidence later. Env-overridable.
    min_dpi: int = 100  # effective DPI below this -> warn.
    blur_warn: float = 60.0  # variance-of-Laplacian below this -> blurry.
    contrast_warn: float = 30.0  # pixel std below this -> low contrast.
    blank_ink_ratio: float = 0.01  # ink fraction below this -> near-blank (skips contrast warn).
    brightness_dark: float = 50.0  # pixel mean below this -> too dark.
    skew_deskew_deg: float = 2.0  # |skew| >= this -> auto-deskew.
    prescan_normalize_width: int = 1000  # downscale width before measuring sharpness.
    assumed_page_height_in: float = 11.0  # US-Letter assumption for effective DPI.
    prescan_timeout_s: float = 120.0  # over this -> 504, not a hang.

    # OCR engine layer (Phase 3). Engines swappable behind a common interface.
    ocr_default_engine: str = "docling"  # used when ?engine= is omitted.
    # Load OCR models at startup so the first request skips the cold download.
    # Off by default (fast boot for tests/dev); turn on for the demo via `make warm`.
    pre_warm_models: bool = False
    ocr_device: str = "cpu"  # "cpu" | "gpu" | "mps".
    # "qwen-vl": a VLM over OpenRouter. No local models (instant boot, bills per
    # call); reuses OPENROUTER_API_KEY and lazily imports the `agent` extra.
    ocr_vlm_model: str = "qwen/qwen3-vl-235b-a22b-instruct"
    ocr_vlm_base_url: str = "https://openrouter.ai/api/v1"
    ocr_confidence_warn: float = 0.80  # avg block confidence below this -> warn.
    ocr_timeout_s: float = 600.0  # generous to absorb a cold model download.
    llm_timeout_s: float = 120.0  # structuring + decision (network LLM).

    # Multi-engine OCR routing + fallback (Phase 3). A doc type may name a
    # preferred engine + ordered fallbacks; otherwise the default chain below is
    # used. The chain advances to the next engine when one raises, returns empty
    # text, or scores below the confidence floor (the last engine is always accepted).
    ocr_fallback_confidence_threshold: float = 0.40  # avg conf below this -> try next engine.
    ocr_default_fallback_engines: list[str] = []  # appended after ocr_default_engine.
    # External OCR service adapter (Digibot/Rossum-style). The adapter is only
    # reachable when an endpoint is configured; the key is read from the env only.
    digibot_endpoint: str = ""  # HTTP endpoint of the external OCR service.
    digibot_api_key: str = ""  # bearer token, if the service requires one.
    digibot_timeout_s: float = 60.0  # per-request timeout for the external call.

    # Structuring layer (Phase 4). LangExtract turns OCR text into validated JSON;
    # the path is lazily imported, and the offline "mock" provider covers tests.
    structuring_provider: str = "langextract"  # "langextract" | "mock"
    # Verified live 2026-05-30 -> deepseek-v4-flash-20260423. Fallback: deepseek-v3.2.
    structuring_model: str = "deepseek/deepseek-v4-flash"
    structuring_base_url: str = "https://openrouter.ai/api/v1"
    structuring_max_char_buffer: int = 8000  # chunk size fed to the model.
    structuring_extraction_passes: int = 2  # >1 improves recall at ~2x latency.
    extraction_confidence_warn: float = 0.60  # overall conf below this -> warn.
    # Per-field review-queue cut-off: a leaf field whose confidence is below this is
    # "at risk" and surfaced for reviewer attention. 0.5 == the ConfidencePill
    # red/amber boundary in the UI. Env-overridable; overridable per-request via ?threshold=.
    field_review_confidence_threshold: float = 0.5
    # Section-aware extraction (accuracy over cost). Partition a document into
    # heading-delimited sections and extract each against its own grounded substrate,
    # then merge — instead of flattening the whole document into one window.
    structuring_sectioning: bool = True  # kill switch: False = always single-blob path.
    structuring_section_min_chars: int = 500  # a raw section shorter than this coalesces into a neighbor.
    structuring_max_sections: int = 40  # circuit breaker: more than this -> whole-doc fallback + warning.
    # Active-learning loop: inject a doc type's past reviewer corrections as extra
    # few-shot examples so the extractor stops repeating the same mistakes. NO-OP for
    # the mock provider or when there are no corrections (spec stays byte-identical).
    few_shot_corrections_enabled: bool = True
    few_shot_max_examples: int = 5

    # Agent decision layer (Phase 5). A single OpenRouter call supplies qualitative
    # judgment; the deterministic rules below run in code and the LLM can never
    # override a hard failure. The "llm" path is lazily imported; "mock" is offline.
    decision_provider: str = "llm"  # "llm" | "mock"
    # Verified live 2026-05-30 -> deepseek-v4-flash-20260423; clean JSON output.
    decision_model: str = "deepseek/deepseek-v4-flash"
    decision_base_url: str = "https://openrouter.ai/api/v1"
    # Business-rule thresholds — editable so they can be tweaked live on camera.
    invoice_auto_approve_max: float = 10000.0  # total over this -> needs_review.
    invoice_total_tolerance: float = 0.01  # |total - (subtotal+tax)| allowance.
    invoice_flag_on_bank_details: bool = False  # True -> bank details = flag.
    contract_value_review_threshold: float = 100000.0  # value over this -> needs_review.
    contract_allowed_governing_law: list[str] = [
        "Delaware",
        "England and Wales",
        "New York",
        "California",
    ]

    # AI doc-type wizard (Phase 3 Wave 1). The assistant agent designs a new doc type
    # conversationally over OpenRouter; the Plannotator subprocess collects review
    # annotations. The "assist" call reuses OPENROUTER_API_KEY. All env-overridable.
    assist_model: str = "deepseek/deepseek-v4-flash"
    assist_base_url: str = "https://openrouter.ai/api/v1"
    assist_timeout_s: float = 120.0  # wizard turn (network LLM, may include a repair pass).
    annotate_ttl_s: float = 600.0  # idle annotation sessions older than this are reaped.

    # Signature detection (Phase 1). A YOLOv8s ONNX model runs as a spatial post-pass
    # over the page images inside structuring, gated by a doc type declaring a
    # ``kind="signature"`` field. Everything is best-effort: the optional ``signatures``
    # extra (onnxruntime + huggingface-hub) is lazily imported and the weights load from
    # a local path (with an optional HF_TOKEN-gated download fallback), so the app boots
    # and structuring runs without the deps or the model file present.
    signature_detection_enabled: bool = True
    signature_model_path: str = "app/models/yolov8s.onnx"  # local weights (relative to backend/).
    signature_model_repo: str = "tech4humans/yolov8s-signature-detector"
    signature_model_file: str = "yolov8s.onnx"
    signature_conf_threshold: float = 0.45  # detections below this are dropped. Calibrated on a
    # real-document eval: true signatures scored >=0.53, false positives (body cursive) <=0.36, so
    # 0.45 sits in that gap — keeps genuine signatures, drops the noise. See docs/signature-extraction.md.
    signature_iou_threshold: float = 0.45  # NMS IoU for overlapping boxes.
    signature_input_size: int = 640  # model input square (letterboxed).
    signature_crop_padding_px: int = 6  # padding added around a detected box before cropping.

    # Classifier stage (Phase 2 multi-document cases). Guesses each file's doc-type
    # before extraction. The default "heuristic" provider is fully offline (token overlap
    # against each doc type's extraction vocabulary); the optional "llm" path lazily
    # imports openai and degrades to no-guess on any failure. Mirrors the ocr/structuring
    # provider naming.
    classify_provider: str = "heuristic"  # "heuristic" | "llm"
    classify_model: str = ""  # OpenRouter slug (only used by the "llm" provider)
    classify_base_url: str = ""  # OpenAI-compatible base URL (only used by the "llm" provider)

    # Reconciler tolerances (Phase 2). How close two candidate values must be to "agree"
    # per kind. Env-overridable so they can be tuned live.
    reconcile_money_abs_tolerance: float = 0.01  # |a - b| within this -> money agrees.
    reconcile_money_pct_tolerance: float = 0.0  # OR within this fraction of the larger value.
    reconcile_date_tolerance_days: int = 3  # dates within this many days agree.
    reconcile_string_fuzzy_threshold: float = 0.85  # SequenceMatcher ratio at/above this agrees.

    # Form-fill mapping layer (Phase 1, Wave 3). A single OpenRouter call suggests
    # which catalogue path each PDF form field binds to; the offline "mock" heuristic
    # (token overlap) is both the no-key fallback and each field's per-field fallback.
    mapping_provider: str = "llm"  # "llm" | "mock"
    mapping_model: str = "deepseek/deepseek-v4-flash"
    mapping_base_url: str = "https://openrouter.ai/api/v1"

    # Authoring-agent layer (Phase 3). A tool-calling OpenRouter agent edits a
    # template's HTML/CSS on request; the offline "mock" provider covers tests.
    # The "llm" path is lazily imported; agent + SSE route land in later waves.
    agent_authoring_provider: str = "llm"  # "llm" | "mock"
    agent_authoring_model: str = "deepseek/deepseek-v4-flash"
    agent_authoring_base_url: str = "https://openrouter.ai/api/v1"
    agent_authoring_max_tool_iterations: int = 6  # tool-call rounds before stopping.
    agent_authoring_timeout_s: float = 120.0  # per-request wall-clock ceiling.

    # Vision-QA layer (Phase 4). A multimodal OpenRouter call judges a rendered
    # template PDF against a reference (or the described HTML) for visual-fidelity
    # issues. The "llm" path is lazily imported; "mock" is offline and the graceful
    # fallback when the key/network/parse fails.
    qa_vision_provider: str = "llm"  # "llm" | "mock"
    qa_vision_model: str = "qwen/qwen3-vl-235b-a22b-instruct"
    qa_vision_base_url: str = "https://openrouter.ai/api/v1"
    qa_timeout_s: float = 180.0  # per-request wall-clock ceiling.
    qa_render_dpi: int = 120  # rasterize the preview PDF to PNG at this DPI.
    qa_max_pages: int = 5  # cap images sent to the judge (adds a truncation warning).

    # Outbound digital signing (Phase 6). Off the inbound pipeline: an APPROVED document
    # can be signed with a real X.509 cert whose embedded CMS validates against a trust
    # chain. "pyhanko" = real (optional dep: uv sync --extra signing); "mock" = offline.
    signing_provider: str = "pyhanko"  # "pyhanko" | "mock"
    signing_level: str = "PAdES-B-B"  # "PAdES-B-B" | "PAdES-B-T" (B-T needs a TSA)
    signing_tsa_url: str = ""  # RFC 3161 TSA URL; enables B-T when set
    signing_field_name: str = "Signature1"
    signing_reason: str = "Approved for transmission"
    signing_location: str = ""
    signing_signer_name: str = "Document Approval Demo Signer"
    signing_ca_common_name: str = "Document Approval Demo CA"
    # Demo server-held seal (custody option A). Self-signed CA+leaf minted on first use.
    # Kept OUTSIDE the /files-served data dir (private keys must never be downloadable).
    # Resolved relative to backend/ like data_dir. Gitignored. NOT for production.
    signing_cert_dir: str = "certs"
    signing_timeout_s: float = 60.0

    # Browser origins allowed to call the API (Vite dev server by default).
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def data_path(self) -> Path:
        """Absolute path to the data dir, resolved relative to backend/."""
        path = Path(self.data_dir)
        return path if path.is_absolute() else BACKEND_ROOT / path

    @property
    def signature_model_full_path(self) -> Path:
        """Absolute path to the signature model weights, resolved relative to backend/."""
        path = Path(self.signature_model_path)
        return path if path.is_absolute() else BACKEND_ROOT / path

    @property
    def signing_cert_path(self) -> Path:
        """Absolute path to the demo signer cert dir, resolved relative to backend/.

        Deliberately kept OUTSIDE ``data_path`` (the /files static mount serves
        ``data/``): private keys under it would otherwise be publicly downloadable.
        """
        path = Path(self.signing_cert_dir)
        return path if path.is_absolute() else BACKEND_ROOT / path


settings = Settings()

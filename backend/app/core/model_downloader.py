"""
app/core/model_downloader.py
────────────────────────────
One-time model download / presence check.

Call `ensure_models()` early in main.py (after runtime_env.configure()).
On the very first run, missing models are downloaded to the standard
Windows cache paths.  Subsequent runs skip the check if a sentinel file
exists at %USERPROFILE%\\.cache\\photo-gallery\\.models_ready.

Models managed:
  1. InsightFace  – buffalo_l  (detection + recognition)
  2. CLIP         – ViT-B/32   (image–text embeddings)
  3. BLIP         – Salesforce/blip-image-captioning-base  (captions)
  4. FaceNet      – vggface2   (face embeddings, via torch.hub)
  MediaPipe is bundled inside the exe — no download needed.
"""

import logging
import os
import threading

_log = logging.getLogger("model_downloader")

# Sentinel file written after a successful download pass
def _sentinel_path() -> str:
    base = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return os.path.join(base, ".cache", "photo-gallery", ".models_ready")


def _mark_ready() -> None:
    path = _sentinel_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("ok")


def _is_ready() -> bool:
    return os.path.isfile(_sentinel_path())


# ─────────────────────────────────────────────────────────────────────────────
# Individual model downloaders
# ─────────────────────────────────────────────────────────────────────────────

def _download_insightface() -> bool:
    """Download InsightFace buffalo_l to %USERPROFILE%\\.insightface\\models\\."""
    try:
        _log.info("Checking InsightFace buffalo_l…")
        from insightface.app import FaceAnalysis
        app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=-1, det_size=(160, 160))  # small size = fast init
        _log.info("InsightFace buffalo_l ✓")
        return True
    except Exception as e:
        _log.error("InsightFace download failed: %s", e)
        return False


def _download_clip() -> bool:
    """Download CLIP ViT-B/32 to %USERPROFILE%\\.cache\\clip\\."""
    try:
        _log.info("Checking CLIP ViT-B/32…")
        import clip
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        clip.load("ViT-B/32", device=device, jit=False)
        _log.info("CLIP ViT-B/32 ✓")
        return True
    except Exception as e:
        _log.error("CLIP download failed: %s", e)
        return False


def _download_blip() -> bool:
    """Download BLIP blip-image-captioning-base to HuggingFace hub cache."""
    try:
        _log.info("Checking BLIP blip-image-captioning-base…")
        from transformers import BlipProcessor, BlipForConditionalGeneration
        MODEL_ID = "Salesforce/blip-image-captioning-base"
        BlipProcessor.from_pretrained(MODEL_ID)
        BlipForConditionalGeneration.from_pretrained(MODEL_ID)
        _log.info("BLIP blip-image-captioning-base ✓")
        return True
    except Exception as e:
        _log.error("BLIP download failed: %s", e)
        return False


def _download_facenet() -> bool:
    """Download FaceNet vggface2 weights to torch hub cache."""
    try:
        _log.info("Checking FaceNet vggface2…")
        from facenet_pytorch import InceptionResnetV1
        InceptionResnetV1(pretrained="vggface2").eval()
        _log.info("FaceNet vggface2 ✓")
        return True
    except Exception as e:
        _log.error("FaceNet download failed: %s", e)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def _run_downloads() -> None:
    """Run all downloads sequentially and write sentinel on success."""
    _log.info("=" * 60)
    _log.info("First-run model setup — downloading AI models…")
    _log.info("This runs once.  Models are stored in your user profile cache.")
    _log.info("=" * 60)

    results = {
        "InsightFace (buffalo_l)": _download_insightface(),
        "CLIP (ViT-B/32)":        _download_clip(),
        "BLIP (captioning-base)": _download_blip(),
        "FaceNet (vggface2)":     _download_facenet(),
    }

    _log.info("-" * 60)
    for name, ok in results.items():
        status = "✓ ready" if ok else "✗ failed (AI feature unavailable)"
        _log.info("  %-32s %s", name, status)
    _log.info("-" * 60)

    if all(results.values()):
        _mark_ready()
        _log.info("All models ready — sentinel written; won't re-check on next run.")
    else:
        _log.warning(
            "Some models failed to download.  The app will run with reduced AI "
            "capabilities.  Re-launch to retry failed downloads."
        )


def ensure_models() -> None:
    """
    Check whether models are present; if not, download them in a background
    thread so the FastAPI server starts immediately without blocking.

    Pass `force=True` to skip the sentinel check (useful for debugging).
    """
    if _is_ready():
        _log.info("Model sentinel found — skipping download check.")
        return

    _log.info("Model sentinel not found — scheduling one-time download…")
    t = threading.Thread(target=_run_downloads, daemon=True, name="model-downloader")
    t.start()

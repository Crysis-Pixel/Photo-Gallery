"""
app/core/runtime_env.py
───────────────────────
Must be imported BEFORE any AI library.

Sets every AI library's cache directory to the standard Windows user-profile
locations so that the frozen PyInstaller executable and the dev venv both
resolve models from the same place.

Default Windows cache paths established here:
  InsightFace  →  %USERPROFILE%\\.insightface
  HuggingFace  →  %USERPROFILE%\\.cache\\huggingface
  Torch Hub    →  %USERPROFILE%\\.cache\\torch
  CLIP         →  %USERPROFILE%\\.cache\\clip
"""

import os

def _userprofile_path(*parts: str) -> str:
    """Return an absolute path under %USERPROFILE%."""
    base = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return os.path.join(base, *parts)


def configure() -> None:
    """Apply all cache-dir environment variables.  Safe to call multiple times."""

    # ── HuggingFace (BLIP, Transformers, tokenizers) ─────────────────────────
    hf_home = _userprofile_path(".cache", "huggingface")
    os.environ["HF_HOME"] = hf_home
    os.environ["HUGGINGFACE_HUB_CACHE"] = os.path.join(hf_home, "hub")
    os.environ["TRANSFORMERS_CACHE"] = os.path.join(hf_home, "hub")

    # ── PyTorch Hub / FaceNet-PyTorch ────────────────────────────────────────
    torch_home = _userprofile_path(".cache", "torch")
    os.environ["TORCH_HOME"] = torch_home

    # ── OpenAI CLIP ──────────────────────────────────────────────────────────
    clip_cache = _userprofile_path(".cache", "clip")
    os.environ["CLIP_CACHE"] = clip_cache

    # ── InsightFace ──────────────────────────────────────────────────────────
    insightface_home = _userprofile_path(".insightface")
    os.environ["INSIGHTFACE_HOME"] = insightface_home

    # Create dirs now so libraries don't fail on first access
    for path in (hf_home, torch_home, clip_cache, insightface_home):
        os.makedirs(path, exist_ok=True)

    print(f"[runtime_env] USERPROFILE={os.environ.get('USERPROFILE')}")
    print(f"[runtime_env] INSIGHTFACE_HOME={insightface_home}")
    print(f"[runtime_env] HF_HOME={hf_home}")
    print(f"[runtime_env] TORCH_HOME={torch_home}")

# -*- mode: python ; coding: utf-8 -*-
"""
photo-gallery-backend.spec
──────────────────────────
Produces a lean (~400–600 MB) backend exe by keeping only code + DLLs.

AI model weight files are NOT bundled — they live in the user's profile
cache and are downloaded on first run by app.core.model_downloader.

What IS kept inside the exe
  • All Python bytecode (via collect_all code/binary components)
  • ONNX Runtime DLLs              (needed at runtime, no equivalent external)
  • MediaPipe .tflite task graphs  (small, embedded in the package — kept)
  • All other shared libraries (.dll / .so / .pyd)

What is EXCLUDED (handled by model_downloader at first run)
  • *.onnx            — InsightFace buffalo_l models
  • *.bin             — HuggingFace weight shards
  • *.safetensors     — HuggingFace safetensor weights
  • *.pt / *.pth      — PyTorch checkpoints (CLIP, FaceNet)
  • *.pkl             — pickled model state
  • *.pb              — TensorFlow protobuf graphs (not mediapipe tflite)
  • clip/bpe_*.txt    — Large BPE vocab files ARE kept (tiny, needed at runtime)
"""

import os
from PyInstaller.utils.hooks import collect_all

# ── Binary patterns to strip (CUDA runtime DLLs — user's system CUDA handles these) ─
# Stripping these drops the exe from ~2.86 GB to ~400 MB.
# The app falls back to CPU automatically if CUDA isn't available at runtime.
# ── Data-file weight extensions to strip ──────────────────────────────────────
EXCLUDE_DATA_EXTS = {".onnx", ".bin", ".safetensors", ".pt", ".pth", ".pkl", ".pb"}
KEEP_PATH_FRAGMENTS = ["mediapipe"]   # keep MediaPipe's bundled tflite graphs

def filter_binaries(raw_binaries):
    # No longer needed, as we installed CPU-only PyTorch
    return [item for item in raw_binaries]


def filter_datas(raw_datas):
    filtered = []
    for src, dest in raw_datas:
        ext = os.path.splitext(src)[1].lower()
        if ext in EXCLUDE_DATA_EXTS:
            if not any(frag in src.lower() for frag in KEEP_PATH_FRAGMENTS):
                continue
        filtered.append((src, dest))
    return filtered


# ── Collect packages ──────────────────────────────────────────────────────────
datas = []
binaries = []
hiddenimports = [
    "PIL",
    "sqlalchemy",
    "fastapi",
    "uvicorn",
    "app.core.ai",
    "app.core.runtime_env",
    "app.core.model_downloader",
    "app.services.tagging_service",
    "setuptools",
]

PACKAGES = [
    "clip",
    "insightface",
    "facenet_pytorch",
    "transformers",
    "mediapipe",
    "tokenizers",
    "huggingface_hub",
    "safetensors",
    "onnxruntime",
]

for pkg in PACKAGES:
    pkg_datas, pkg_bins, pkg_hidden = collect_all(pkg)
    datas    += filter_datas(pkg_datas)
    binaries += filter_binaries(pkg_bins)
    hiddenimports += pkg_hidden


# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    ["app\\main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

a.binaries = filter_binaries(a.binaries)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="photo-gallery-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[
        # Don't UPX-compress these — they break when compressed
        "vcruntime140.dll",
        "python3*.dll",
        "onnxruntime*.dll",
    ],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

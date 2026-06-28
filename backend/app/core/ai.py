"""
app/core/ai.py
──────────────
Lazy-loaded AI model registry.

NO model is loaded at import time.
Each model is loaded on first use and cached globally.
All loaders are exception-safe and will never crash the application.
"""

import logging
import os

# ── Logger ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[AI] %(levelname)s %(asctime)s – %(message)s",
    datefmt="%H:%M:%S",
)
_log = logging.getLogger("ai_models")

# ── Expose PyTorch-bundled CUDA/cuDNN DLLs to onnxruntime ────────────────────
# onnxruntime-gpu loads onnxruntime_providers_cuda.dll which depends on
# cudart64_12.dll, cublas64_12.dll, cudnn64_8.dll etc.  PyTorch bundles
# all of these in its own `lib` folder.  On Python 3.8+ Windows the DLL
# search path for extension modules must be set via os.add_dll_directory();
# modifying os.environ['PATH'] alone has no effect on C extension DLLs.
try:
    import torch as _torch_init
    _torch_lib = os.path.join(os.path.dirname(_torch_init.__file__), "lib")
    if os.path.isdir(_torch_lib):
        os.add_dll_directory(_torch_lib)          # Python 3.8+ Windows
        os.environ["PATH"] = _torch_lib + os.pathsep + os.environ.get("PATH", "")
        _log.info("Registered torch lib for DLL search: %s", _torch_lib)
except Exception:
    pass  # torch not installed or non-Windows — CPU-only fallback is fine

# ── Feature flags (updated to True on successful load) ───────────────────────

INSIGHTFACE_AVAILABLE: bool = False
CLIP_AVAILABLE: bool = False
BLIP_AVAILABLE: bool = False
FACENET_AVAILABLE: bool = False

# ── Private caches (do NOT access directly – use the getters below) ──────────

_face_analyzer = None          # InsightFace FaceAnalysis
_clip_model = None             # CLIP model
_clip_preprocess = None        # CLIP image preprocessor
_clip_device = None            # device string used by CLIP/BLIP/FaceNet
_blip_processor = None         # BLIP BlipProcessor
_blip_model = None             # BLIP BlipForConditionalGeneration
_mtcnn = None                  # FaceNet MTCNN detector
_resnet = None                 # FaceNet InceptionResnetV1

_insightface_attempted = False
_clip_attempted = False
_blip_attempted = False
_facenet_attempted = False


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _insightface_root() -> str:
    """Return the InsightFace root directory.

    Reads INSIGHTFACE_HOME (set by runtime_env.configure()) so that both
    the dev venv and the frozen PyInstaller exe resolve the same path.
    InsightFace does NOT honour this env-var itself — it only accepts a
    `root=` constructor argument, so we must bridge the two.
    """
    return os.environ.get("INSIGHTFACE_HOME") or os.path.join(
        os.environ.get("USERPROFILE") or os.path.expanduser("~"),
        ".insightface",
    )

def _get_device() -> str:
    """Return 'cuda' if a GPU is available, otherwise 'cpu'."""
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


# ─────────────────────────────────────────────────────────────────────────────
# 1. InsightFace
# ─────────────────────────────────────────────────────────────────────────────

def get_insightface():
    """
    Return the InsightFace FaceAnalysis instance, loading it on first call.
    Returns None if the model cannot be loaded.
    """
    global _face_analyzer, INSIGHTFACE_AVAILABLE, _insightface_attempted

    if _insightface_attempted:
        return _face_analyzer
    _insightface_attempted = True

    try:
        _log.info("Loading InsightFace (buffalo_l)…")
        import torch
        from insightface.app import FaceAnalysis

        cuda_ok = torch.cuda.is_available()

        if cuda_ok:
            _log.info("Attempting InsightFace with CUDAExecutionProvider…")
            try:
                _face_analyzer = FaceAnalysis(
                    name="buffalo_l",
                    root=_insightface_root(),
                    providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
                )
                _face_analyzer.prepare(ctx_id=0, det_size=(640, 640))
                _log.info("InsightFace loaded on CUDA.")
            except Exception as cuda_err:
                _log.warning(
                    "CUDAExecutionProvider failed (%s) – falling back to CPU.",
                    cuda_err,
                )
                _face_analyzer = FaceAnalysis(
                    name="buffalo_l",
                    root=_insightface_root(),
                    providers=["CPUExecutionProvider"],
                )
                _face_analyzer.prepare(ctx_id=-1, det_size=(640, 640))
                _log.info("InsightFace loaded on CPU (CUDA fallback).")
        else:
            _face_analyzer = FaceAnalysis(
                name="buffalo_l",
                root=_insightface_root(),
                providers=["CPUExecutionProvider"],
            )
            _face_analyzer.prepare(ctx_id=-1, det_size=(640, 640))
            _log.info("InsightFace loaded on CPU.")

        INSIGHTFACE_AVAILABLE = True
        _log.info("InsightFace ready.")
    except Exception as e:
        _log.error("InsightFace failed to load: %s", e)
        _face_analyzer = None
        INSIGHTFACE_AVAILABLE = False

    return _face_analyzer


# ─────────────────────────────────────────────────────────────────────────────
# 2. CLIP
# ─────────────────────────────────────────────────────────────────────────────

def get_clip():
    """
    Return (clip_model, preprocess, device) tuple, loading on first call.
    Returns (None, None, 'cpu') if the model cannot be loaded.
    """
    global _clip_model, _clip_preprocess, _clip_device, CLIP_AVAILABLE, _clip_attempted

    if _clip_attempted:
        return _clip_model, _clip_preprocess, _clip_device
    _clip_attempted = True

    try:
        _log.info("Loading CLIP (ViT-B/32)…")
        import clip as _clip_lib

        device = _get_device()
        try:
            _clip_model, _clip_preprocess = _clip_lib.load(
                "ViT-B/32", device=device, jit=False
            )
        except RuntimeError:
            _log.warning("CLIP GPU load failed, falling back to CPU.")
            device = "cpu"
            _clip_model, _clip_preprocess = _clip_lib.load(
                "ViT-B/32", device=device, jit=False
            )
        _clip_device = device
        CLIP_AVAILABLE = True
        _log.info("CLIP loaded successfully on %s.", device)
    except Exception as e:
        _log.error("CLIP failed to load: %s", e)
        _clip_model = None
        _clip_preprocess = None
        _clip_device = "cpu"
        CLIP_AVAILABLE = False

    return _clip_model, _clip_preprocess, _clip_device


# ─────────────────────────────────────────────────────────────────────────────
# 3. BLIP
# ─────────────────────────────────────────────────────────────────────────────

def get_blip():
    """
    Return (blip_processor, blip_model, device) tuple, loading on first call.
    Uses local_files_only=True to prevent runtime downloads.
    Returns (None, None, 'cpu') if the model cannot be loaded.
    """
    global _blip_processor, _blip_model, _clip_device, BLIP_AVAILABLE, _blip_attempted

    if _blip_attempted:
        return _blip_processor, _blip_model, _clip_device
    _blip_attempted = True

    MODEL_ID = "Salesforce/blip-image-captioning-base"
    try:
        _log.info("Loading BLIP (%s)…", MODEL_ID)
        from transformers import BlipProcessor, BlipForConditionalGeneration

        device = _get_device()
        _blip_processor = BlipProcessor.from_pretrained(
            MODEL_ID, local_files_only=True
        )
        _blip_model = BlipForConditionalGeneration.from_pretrained(
            MODEL_ID, local_files_only=True
        ).to(device)

        if device == "cuda":
            import torch
            _blip_model = _blip_model.half()

        _clip_device = device
        BLIP_AVAILABLE = True
        _log.info("BLIP loaded successfully on %s.", device)
    except Exception as e:
        _log.error("BLIP failed to load: %s", e)
        _blip_processor = None
        _blip_model = None
        BLIP_AVAILABLE = False

    return _blip_processor, _blip_model, _clip_device


# ─────────────────────────────────────────────────────────────────────────────
# 4. FaceNet (MTCNN + InceptionResnetV1)
# ─────────────────────────────────────────────────────────────────────────────

def get_facenet():
    """
    Return (mtcnn, resnet, device) tuple, loading on first call.
    Returns (None, None, 'cpu') if the model cannot be loaded.
    """
    global _mtcnn, _resnet, _clip_device, FACENET_AVAILABLE, _facenet_attempted

    if _facenet_attempted:
        return _mtcnn, _resnet, _get_device()
    _facenet_attempted = True

    try:
        _log.info("Loading FaceNet (MTCNN + InceptionResnetV1)…")
        from facenet_pytorch import MTCNN, InceptionResnetV1

        device = _get_device()
        _mtcnn = MTCNN(keep_all=True, device=device)
        _resnet = InceptionResnetV1(pretrained="vggface2").eval().to(device)
        FACENET_AVAILABLE = True
        _log.info("FaceNet loaded successfully on %s.", device)
    except Exception as e:
        _log.error("FaceNet failed to load: %s", e)
        _mtcnn = None
        _resnet = None
        FACENET_AVAILABLE = False

    return _mtcnn, _resnet, _get_device()



# ─────────────────────────────────────────────────────────────────────────────
# High-level convenience functions
# ─────────────────────────────────────────────────────────────────────────────

def get_image_description(image) -> str | None:
    """
    Generate a caption for *image* (PIL.Image) using BLIP.
    Returns None if BLIP is unavailable or an error occurs.
    """
    processor, blip, device = get_blip()
    if processor is None or blip is None:
        return None

    try:
        import torch

        inputs = processor(image, return_tensors="pt").to(device)
        if device == "cuda":
            inputs = {
                k: v.half() if v.dtype == torch.float32 else v
                for k, v in inputs.items()
            }
        with torch.no_grad():
            out = blip.generate(**inputs)
        return processor.decode(out[0], skip_special_tokens=True)
    except Exception as e:
        _log.error("Error generating image description: %s", e)
        return None


def classify_image_clip(image, labels: list[str]) -> str | None:
    """
    Classify *image* (PIL.Image) against *labels* using CLIP.
    Returns the best-matching label string, or None if CLIP is unavailable.
    """
    clip_model, preprocess, device = get_clip()
    if clip_model is None:
        return None

    try:
        import clip as _clip_lib
        import torch

        tokens = _clip_lib.tokenize(labels).to(device)
        with torch.no_grad():
            feat = clip_model.encode_image(
                preprocess(image).unsqueeze(0).to(device)
            ).float()
            feat /= feat.norm(dim=-1, keepdim=True)
            text_feat = clip_model.encode_text(tokens).float()
            text_feat /= text_feat.norm(dim=-1, keepdim=True)
            logits = (feat @ text_feat.T).softmax(dim=-1)
        return labels[logits[0].argmax().item()]
    except Exception as e:
        _log.error("CLIP classification error: %s", e)
        return None


def detect_faces_insightface(image_np) -> list:
    """
    Run InsightFace on a numpy image array.
    Returns a list of face objects, or [] if unavailable / on error.
    """
    analyzer = get_insightface()
    if analyzer is None:
        return []
    try:
        return analyzer.get(image_np) or []
    except Exception as e:
        _log.error("InsightFace detection error: %s", e)
        return []


def detect_faces_facenet(image):
    """
    Run FaceNet MTCNN on a PIL image.
    Returns (boxes, embeddings) or (None, None) on failure.
    """
    mtcnn, resnet, device = get_facenet()
    if mtcnn is None or resnet is None:
        return None, None

    try:
        import torch

        boxes, _ = mtcnn.detect(image)
        if boxes is None:
            return None, None
        face_tensors = mtcnn.extract(image, boxes, None)
        if face_tensors is None:
            return boxes, None
        face_batch = (
            torch.stack(face_tensors).to(device)
            if isinstance(face_tensors, list)
            else face_tensors.to(device)
        )
        with torch.no_grad():
            embs = (
                torch.nn.functional.normalize(resnet(face_batch), p=2, dim=1)
                .cpu()
                .numpy()
            )
        return boxes, embs
    except Exception as e:
        _log.error("FaceNet detection error: %s", e)
        return None, None


def is_model_downloaded(name: str) -> bool:
    """Check if the model files are already downloaded/available on disk."""
    import os
    home = os.path.expanduser("~")
    
    if name == "insightface":
        if INSIGHTFACE_AVAILABLE:
            return True
        path = os.path.join(home, ".insightface", "models", "buffalo_l")
        if os.path.exists(path):
            try:
                return any(f.endswith(".onnx") for f in os.listdir(path))
            except Exception:
                return False
        return False

    elif name == "clip":
        if CLIP_AVAILABLE:
            return True
        path = os.path.join(home, ".cache", "clip", "ViT-B-32.pt")
        return os.path.isfile(path)

    elif name == "blip":
        if BLIP_AVAILABLE:
            return True
        path = os.path.join(home, ".cache", "huggingface", "hub", "models--Salesforce--blip-image-captioning-base")
        if os.path.exists(path):
            try:
                sn_path = os.path.join(path, "snapshots")
                if os.path.exists(sn_path):
                    return len(os.listdir(sn_path)) > 0
                return True
            except Exception:
                return False
        return False

    elif name == "facenet":
        if FACENET_AVAILABLE:
            return True
        path = os.path.join(home, ".cache", "torch", "hub", "checkpoints", "20180402-114759-vggface2.pt")
        return os.path.isfile(path)

    return False


def status_report() -> dict:
    """Return a dict summarising which models are downloaded and loadable."""
    return {
        "insightface": is_model_downloaded("insightface"),
        "clip": is_model_downloaded("clip"),
        "blip": is_model_downloaded("blip"),
        "facenet": is_model_downloaded("facenet"),
    }


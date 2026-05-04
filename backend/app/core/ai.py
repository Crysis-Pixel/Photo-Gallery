import os
import json
import numpy as np
import torch
from PIL import Image, ImageOps
from app.utils import generate_random_color

# ── InsightFace Setup ───────────────────────────────────────────────────────
try:
    import insightface
    from insightface.app import FaceAnalysis
    import cv2

    providers = ['CPUExecutionProvider']
    if torch.cuda.is_available():
        providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']

    face_analyzer = FaceAnalysis(
        name='buffalo_l',
        providers=providers
    )
    face_analyzer.prepare(ctx_id=0 if torch.cuda.is_available() else -1, det_size=(640, 640))
    INSIGHTFACE_AVAILABLE = True
    print("InsightFace loaded successfully with buffalo_l model")
except Exception as e:
    print(f"InsightFace failed to load: {e}")
    INSIGHTFACE_AVAILABLE = False


# ── CLIP Setup ──────────────────────────────────────────────────────────────
try:
    import clip
except ImportError:
    from clip import clip

device = "cuda" if torch.cuda.is_available() else "cpu"
try:
    model, preprocess = clip.load("ViT-B/32", device=device, jit=False)
except RuntimeError:
    device = "cpu"
    model, preprocess = clip.load("ViT-B/32", device=device, jit=False)


# ── BLIP Setup ──────────────────────────────────────────────────────────────
try:
    from transformers import BlipProcessor, BlipForConditionalGeneration
    blip_processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
    blip_model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base").to(device)
    if device == "cuda":
        blip_model = blip_model.half()
    BLIP_AVAILABLE = True
except Exception as e:
    print(f"BLIP model not available: {e}")
    BLIP_AVAILABLE = False


# ── FaceNet Setup ───────────────────────────────────────────────────────────
try:
    from facenet_pytorch import MTCNN, InceptionResnetV1
    mtcnn = MTCNN(keep_all=True, device=device)
    resnet = InceptionResnetV1(pretrained='vggface2').eval().to(device)
    FACENET_AVAILABLE = True
except Exception as e:
    print(f"facenet-pytorch not available: {e}")
    FACENET_AVAILABLE = False


# ── MediaPipe Setup ─────────────────────────────────────────────────────────
try:
    import mediapipe as mp
    MEDIAPIPE_AVAILABLE = True
except Exception as e:
    print(f"MediaPipe not available: {e}")
    MEDIAPIPE_AVAILABLE = False


def get_image_description(image: Image.Image) -> str:
    if not BLIP_AVAILABLE:
        return None
    try:
        inputs = blip_processor(image, return_tensors="pt").to(device)
        if device == "cuda":
            inputs = {k: v.half() if v.dtype == torch.float32 else v for k, v in inputs.items()}
        with torch.no_grad():
            out = blip_model.generate(**inputs)
        description = blip_processor.decode(out[0], skip_special_tokens=True)
        return description
    except Exception as e:
        print(f"Error generating image description: {str(e)}")
        return None

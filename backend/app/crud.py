from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from app.models import File, FolderConfig, Person, Face
from app.schemas import FileCreate, FileUpdate
from sqlalchemy.exc import IntegrityError
import torch
from PIL import Image, ImageOps
import mediapipe as mp
import os
import re
import json
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from app.utils import generate_random_color, get_default_person_color, THUMB_DIR, THUMB_W, THUMB_H

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


WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def resolve_folder_path(folder_path: str) -> str:
    if not folder_path:
        return folder_path
    if os.path.isabs(folder_path):
        return os.path.abspath(folder_path)

    candidate = os.path.abspath(os.path.join(WORKSPACE_ROOT, folder_path))
    if os.path.exists(candidate):
        return candidate

    if folder_path == os.path.basename(WORKSPACE_ROOT):
        return WORKSPACE_ROOT

    best_match = None
    best_depth = None
    for root, dirs, _ in os.walk(WORKSPACE_ROOT):
        for d in dirs:
            if d == folder_path:
                candidate_dir = os.path.abspath(os.path.join(root, d))
                depth = len(os.path.relpath(candidate_dir, WORKSPACE_ROOT).split(os.sep))
                if best_match is None or depth < best_depth:
                    best_match = candidate_dir
                    best_depth = depth
    if best_match:
        return best_match

    return candidate


import random

def choose_person_color(db: Session) -> str:
    # Use a set for faster lookup
    used_colors = {p.color for p in db.query(Person.color).filter(Person.color != None).all()}
    
    # Try to find a unique color
    for _ in range(200):
        color = generate_random_color()
        if color not in used_colors:
            return color
            
    return generate_random_color()



try:
    import clip
except ImportError:
    from clip import clip

device = "cuda" if torch.cuda.is_available() else "cpu"
try:
    # CLIP sometimes has issues with .half() in its forward pass, so we keep it in float32.
    # The batching alone will provide a significant speedup.
    model, preprocess = clip.load("ViT-B/32", device=device, jit=False)
except RuntimeError:
    device = "cpu"
    model, preprocess = clip.load("ViT-B/32", device=device, jit=False)

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

try:
    from facenet_pytorch import MTCNN, InceptionResnetV1
    mtcnn = MTCNN(keep_all=True, device=device)
    resnet = InceptionResnetV1(pretrained='vggface2').eval().to(device)
    FACENET_AVAILABLE = True
except Exception as e:
    print(f"facenet-pytorch not available: {e}")
    FACENET_AVAILABLE = False


def generate_thumbnail(db_file: File) -> bool:
    """Pre-generate a WebP thumbnail for a file if it doesn't exist."""
    thumb_path = os.path.join(THUMB_DIR, f"{db_file.id}.webp")
    if os.path.exists(thumb_path):
        return True

    if not os.path.exists(db_file.path):
        return False

    try:
        ext = os.path.splitext(db_file.path)[1].lower()
        video_exts = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
        
        if ext in video_exts:
            try:
                import cv2
                cap = cv2.VideoCapture(db_file.path)
                cap.set(cv2.CAP_PROP_POS_MSEC, 1000)
                ret, frame = cap.read()
                if not ret:
                    cap.set(cv2.CAP_PROP_POS_MSEC, 0)
                    ret, frame = cap.read()
                cap.release()
                if not ret:
                    return False
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame_rgb)
            except Exception:
                return False
        else:
            img = Image.open(db_file.path)
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")

        # Cover-crop to exact card dimensions
        from PIL import ImageOps as _io
        img = _io.fit(img, (THUMB_W, THUMB_H), method=Image.LANCZOS)
        img.save(thumb_path, "WEBP", quality=82, method=4)
        return True
    except Exception as e:
        print(f"[thumbnail-gen] Failed for {db_file.path}: {e}")
        return False


# ── Session helper ─────────────────────────────────────────────────────────────

def _safe_rollback(db: Session):
    try:
        db.rollback()
    except Exception:
        pass


# ── Image helpers ──────────────────────────────────────────────────────────────

def get_image_description(image: Image.Image) -> str:
    if not BLIP_AVAILABLE:
        return None
    try:
        inputs = blip_processor(image, return_tensors="pt").to(device)
        if device == "cuda":
            # Convert float inputs to half to match the model
            inputs = {k: v.half() if v.dtype == torch.float32 else v for k, v in inputs.items()}
        with torch.no_grad():
            out = blip_model.generate(**inputs)
        description = blip_processor.decode(out[0], skip_special_tokens=True)
        return description
    except Exception as e:
        print(f"Error generating image description: {str(e)}")
        return None


def sanitize_description(text: str) -> str:
    if not text:
        return None
    text = re.sub(r"\b(\w+)(?:\s+\1\b)+", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    max_len = 250
    if len(text) > max_len:
        text = text[: max_len - 3].rstrip() + "..."
    return text


# ── Embedding helpers ──────────────────────────────────────────────────────────

def best_similarity(person: Person, emb) -> float:
    encodings_to_check = []
    if person.encoding:
        try:
            encodings_to_check.append(np.array(json.loads(person.encoding), dtype=np.float32))
        except Exception:
            pass
    if person.sample_encodings:
        try:
            for s in json.loads(person.sample_encodings)[:5]:
                encodings_to_check.append(np.array(s, dtype=np.float32))
        except Exception:
            pass

    best = -1.0
    for enc in encodings_to_check:
        if enc.shape != emb.shape:
            continue
        denom = float(np.linalg.norm(enc)) * float(np.linalg.norm(emb))
        if denom > 0:
            best = max(best, float(np.dot(enc, emb) / denom))
    return best


def update_person_encoding(person: Person, emb):
    if person.encoding:
        try:
            old_enc = np.array(json.loads(person.encoding), dtype=np.float32)
            new_enc = (old_enc + emb) / 2.0
            norm = np.linalg.norm(new_enc)
            if norm > 0:
                new_enc /= norm
            person.encoding = json.dumps(new_enc.tolist())
        except Exception:
            person.encoding = json.dumps(emb.tolist())
    else:
        person.encoding = json.dumps(emb.tolist())

    try:
        samples = json.loads(person.sample_encodings or "[]")
    except Exception:
        samples = []
    samples.append(emb.tolist())
    person.sample_encodings = json.dumps(samples[-5:])


def _create_new_person(db: Session, emb) -> Optional[Person]:
    new_person = Person(
        name="",
        color=choose_person_color(db),
        encoding=json.dumps(emb.tolist()),
        sample_encodings=json.dumps([emb.tolist()])
    )
    db.add(new_person)
    db.flush()
    new_person.name = f"Person {new_person.id}"
    db.flush()
    return new_person


# ── Batch Auto-tagging Engine ──────────────────────────────────────────────────

def batch_auto_tag_files(
    db: Session,
    db_files: List[File],
    tag_category=True,
    tag_scenario=True,
    tag_faces=True,
    batch_size=32
):
    """
    Process a list of files in batches for maximum GPU utilization and faster I/O.
    """
    if not db_files:
        return
    
    # Filter out videos - they are handled separately or skipped
    photos = [f for f in db_files if f.file_type == "photo"]
    videos = [f for f in db_files if f.file_type == "video"]
    
    # Handle videos simply
    for v in videos:
        if tag_category and not v.category:
            v.category = "video"
        v.face_scanned = True
        db.add(v)
    
    if not photos:
        db.commit()
        return

    # Helper for parallel image loading
    def load_image(file_path):
        try:
            img = Image.open(file_path)
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            return img
        except Exception as e:
            print(f"[load error] {file_path}: {e}")
            return None

    # Process in batches
    for i in range(0, len(photos), batch_size):
        batch = photos[i:i + batch_size]
        batch_paths = [f.path for f in batch]
        batch_num = (i // batch_size) + 1
        total_batches = (len(photos) + batch_size - 1) // batch_size
        
        print(f"[batch {batch_num}/{total_batches}] Loading {len(batch)} images...")
        
        # 1. Parallel loading
        import time as time_module
        load_start = time_module.time()
        with ThreadPoolExecutor(max_workers=min(len(batch), 4)) as executor:
            images = list(executor.map(load_image, batch_paths))
        load_time = time_module.time() - load_start
        
        # Filter out failed loads
        valid_indices = [idx for idx, img in enumerate(images) if img is not None]
        if not valid_indices:
            print(f"[batch {batch_num}/{total_batches}] No valid images loaded, skipping batch")
            continue
            
        valid_batch = [batch[idx] for idx in valid_indices]
        valid_images = [images[idx] for idx in valid_indices]
        print(f"[batch {batch_num}/{total_batches}] Loaded {len(valid_images)}/{len(batch)} images in {load_time:.1f}s")
        
        # 2. Batch Category (CLIP)
        if tag_category:
            try:
                print(f"[batch {batch_num}/{total_batches}] Categorizing with CLIP...")
                cat_start = time_module.time()
                category_labels = [
                    "selfie", "group photo", "family photo", "birthday", "wedding", 
                    "party", "graduation", "holiday", "travel", "nature", "cityscape", 
                    "beach", "indoor", "food", "pet", "car", "screenshot", "document",
                    "anime", "artwork", "meme"
                ]
                category_tokens = clip.tokenize(category_labels).to(device)
                
                # Preprocess batch
                preprocessed_images = torch.stack([preprocess(img) for img in valid_images]).to(device)
                # Keep CLIP in float32 for stability

                with torch.no_grad():
                    image_features = model.encode_image(preprocessed_images)
                    category_features = model.encode_text(category_tokens)
                    
                    # Convert to float for numerical stability and to avoid mixed-precision issues
                    image_features = image_features.float()
                    category_features = category_features.float()
                    
                    # Normalize features
                    image_features /= image_features.norm(dim=-1, keepdim=True)
                    category_features /= category_features.norm(dim=-1, keepdim=True)
                    
                    logits = (image_features @ category_features.T).softmax(dim=-1)
                    
                for idx, db_file in enumerate(valid_batch):
                    if not db_file.category:
                        best_idx = logits[idx].argmax().item()
                        db_file.category = category_labels[best_idx]
                cat_time = time_module.time() - cat_start
                print(f"[batch {batch_num}/{total_batches}] CLIP done in {cat_time:.1f}s")
            except Exception as e:
                print(f"[batch category error]: {e}")

        # 3. Batch Scenario (BLIP)
        if tag_scenario and BLIP_AVAILABLE:
            try:
                print(f"[batch {batch_num}/{total_batches}] Generating descriptions with BLIP...")
                blip_start = time_module.time()
                # BLIP doesn't support easy batching in this version without more complex code,
                # but we can still loop over our preloaded images to save I/O time.
                scenario_count = 0
                for idx, (db_file, img) in enumerate(zip(valid_batch, valid_images)):
                    if not db_file.scenario:
                        description = get_image_description(img)
                        if description:
                            db_file.scenario = sanitize_description(description)
                            scenario_count += 1
                blip_time = time_module.time() - blip_start
                print(f"[batch {batch_num}/{total_batches}] BLIP done in {blip_time:.1f}s ({scenario_count} descriptions)")
            except Exception as e:
                print(f"[batch scenario error]: {e}")

        # 4. Faces (InsightFace/FaceNet)
        if tag_faces:
            # Free up PyTorch cache so ONNX Runtime (InsightFace) has enough VRAM and doesn't crash the server
            if device == "cuda":
                torch.cuda.empty_cache()

            # Faces are harder to batch because InsightFace doesn't support it well,
            # so we process them sequentially but using our pre-loaded images.
            SIM_THRESHOLD = 0.65
            MIN_FACE_RATIO = 0.04
            
            print(f"[batch {batch_num}/{total_batches}] Detecting faces...")
            import time as time_module
            face_start = time_module.time()
            face_count = 0
            
            for face_idx, (db_file, img) in enumerate(zip(valid_batch, valid_images)):
                try:
                    # Pre-generate thumbnail while we have the image in memory (if it's a photo)
                    # Note: generate_thumbnail handles checking if it already exists
                    generate_thumbnail(db_file)

                    # Check if faces are already tagged
                    has_faces = db.query(Face).filter(Face.file_id == db_file.id).first() is not None
                    if has_faces:
                        db_file.face_scanned = True
                        continue

                    # Skip face detection for anime and meme categories in batch mode
                    if db_file.category in ["anime", "meme"]:
                        db_file.face_scanned = True
                        continue

                    # Clear existing faces if re-detecting (shouldn't happen with the check above, but for safety)
                    # db.query(Face).filter(Face.file_id == db_file.id).delete(synchronize_session=False)
                    
                    if INSIGHTFACE_AVAILABLE:
                        _tag_faces_insightface(db, db_file, img, np, SIM_THRESHOLD, MIN_FACE_RATIO, DET_THRESH=0.3)
                    elif FACENET_AVAILABLE:
                        _tag_faces_facenet(db, db_file, img, np, SIM_THRESHOLD)
                    else:
                        _tag_faces_mediapipe(db, db_file, img, np)
                    
                    db_file.face_scanned = True
                    face_count += 1
                except Exception as fe:
                    print(f"[batch face error] {db_file.path}: {fe}")
                    # Clear CUDA cache if it's a memory error
                    if "out of memory" in str(fe).lower():
                        torch.cuda.empty_cache()

        # 5. Save batch
        try:
            face_time = time_module.time() - face_start
            db.commit()
            for f in valid_batch:
                db.refresh(f)
            print(f"[batch {batch_num}/{total_batches}] ✓ Complete ({len(valid_batch)} images, {face_count} with faces) in {face_time:.1f}s")
        except Exception as e:
            print(f"[batch commit error]: {e}")
            db.rollback()


# ── Auto-tagging ───────────────────────────────────────────────────────────────

def auto_tag_file(
    db: Session,
    db_file: File,
    tag_category=True,
    tag_scenario=True,
    tag_faces=True,
    force_faces=False
):
    """Auto-tag a file - skip processing for videos"""
    file_path = db_file.path
    if not os.path.exists(file_path):
        return db_file

    # Skip AI processing for video files
    if db_file.file_type == "video":
        # Just set basic video info if missing
        if tag_category and not db_file.category:
            db_file.category = "video"
        # if tag_scenario and not db_file.scenario:
        #     db_file.scenario = f"Video: {os.path.basename(file_path)}"
        db.commit()
        db.refresh(db_file)
        return db_file

    # Rest of the existing image processing code...
    try:
        image = Image.open(file_path)
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")

        # ───────────── CATEGORY ─────────────
        if tag_category:
            try:
                category_labels = [
                    # People & social
                    "selfie", "group photo", "family photo",
                    # Events & moments  
                    "birthday", "wedding", "party", "graduation", "holiday",
                    # Places & travel
                    "travel", "nature", "cityscape", "beach", "indoor",
                    # Objects & misc
                    "food", "pet", "car", "screenshot", "document",
                    # Art & media
                    "anime", "artwork", "meme", 
                ]
                category_tokens = clip.tokenize(category_labels).to(device)

                with torch.no_grad():
                    img_tensor = preprocess(image).unsqueeze(0).to(device)
                    # CLIP stays in float32
                        
                    image_features = model.encode_image(img_tensor)
                    category_features = model.encode_text(category_tokens)
                    
                    # Convert to float for normalization and softmax stability
                    image_features = image_features.float()
                    category_features = category_features.float()
                    
                    image_features /= image_features.norm(dim=-1, keepdim=True)
                    category_features /= category_features.norm(dim=-1, keepdim=True)
                    
                    category_logits = (image_features @ category_features.T).softmax(dim=-1)
                    best_category_idx = category_logits[0].argmax().item()

                db_file.category = category_labels[best_category_idx]

            except Exception as e:
                print(f"[category error] {file_path}: {e}")

        # ───────────── SCENARIO ─────────────
        if tag_scenario:
            try:
                description = get_image_description(image)
                if description:
                    db_file.scenario = sanitize_description(description)
            except Exception as e:
                print(f"[scenario error] {file_path}: {e}")

        # ───────────── FACES ─────────────
        if tag_faces:
            # Skip face detection for anime and meme unless forced (e.g. via individual rescan button)
            if not force_faces and db_file.category in ["anime", "meme"]:
                # print(f"[face skip] Skipping face detection for {db_file.category}: {file_path}")
                pass
            else:
                try:
                    SIM_THRESHOLD = 0.60
                    MIN_FACE_RATIO = 0.01

                    # Clear existing faces if re-detecting
                    db.query(Face).filter(
                        Face.file_id == db_file.id
                    ).delete(synchronize_session=False)

                    if INSIGHTFACE_AVAILABLE:
                        _tag_faces_insightface(
                            db, db_file, image, np, SIM_THRESHOLD, MIN_FACE_RATIO, DET_THRESH=0.1
                        )
                    elif FACENET_AVAILABLE:
                        _tag_faces_facenet(
                            db, db_file, image, np, SIM_THRESHOLD
                        )
                    else:
                        _tag_faces_mediapipe(
                            db, db_file, image, np
                        )

                except Exception as face_e:
                    print(f"[face error] {file_path}: {face_e}")
                    db_file.person_name = None
                
                db_file.face_scanned = True

        # ───────────── SAVE ─────────────
        db.commit()
        db.refresh(db_file)

    except Exception as e:
        print(f"[auto_tag ERROR] {file_path}: {e}")
        _safe_rollback(db)

    return db_file


def _tag_faces_insightface(db: Session, db_file: File, image: Image.Image, np,
                            SIM_THRESHOLD: float = 0.65,
                            MIN_FACE_RATIO: float = 0.01,
                            DET_THRESH: float = 0.5):
    if not INSIGHTFACE_AVAILABLE:
        db_file.person_name = None
        return

    try:
        img_np = np.array(image.convert("RGB"))
        height, width = img_np.shape[:2]
        min_face_area = (width * height) * (MIN_FACE_RATIO ** 2)

        faces = face_analyzer.get(img_np)
        if not faces:
            db_file.person_name = None
            return

        persons = db.query(Person).all()
        used_person_ids = []
        valid_faces = []

        for face in faces:
            if face.embedding is None:
                continue
            if getattr(face, 'det_score', 0.0) < DET_THRESH:
                continue
            bbox = face.bbox.astype(int)
            face_width = bbox[2] - bbox[0]
            face_height = bbox[3] - bbox[1]
            face_area = face_width * face_height
            if face_area < min_face_area:
                print(f"[insightface-skip-small] file={db_file.path} face_size={face_width}x{face_height}")
                continue
            valid_faces.append(face)

        if not valid_faces:
            db_file.person_name = None
            return

        for face in valid_faces:
            emb = face.embedding.astype(np.float32)

            best_sim = -1.0
            best_person = None
            for person in persons:
                # Avoid double-tagging the same person in one photo
                if person.id in used_person_ids:
                    continue
                sim = best_similarity(person, emb)
                if sim > best_sim:
                    best_sim = sim
                    best_person = person

            if best_sim >= SIM_THRESHOLD and best_person is not None:
                matched_person = best_person
                update_person_encoding(matched_person, emb)
                db.add(matched_person)
                print(f"[insightface-match] file={os.path.basename(db_file.path)} "
                      f"person={matched_person.name} sim={best_sim:.4f}")
            else:
                matched_person = _create_new_person(db, emb)
                if matched_person is None:
                    continue
                persons.append(matched_person)
                print(f"[insightface-new] file={os.path.basename(db_file.path)} "
                      f"created Person {matched_person.id} sim_to_best={best_sim:.4f}")

            face_row = Face(
                file_id=db_file.id, 
                person_id=matched_person.id,
                box_left=float(face.bbox[0] / width),
                box_top=float(face.bbox[1] / height),
                box_width=float((face.bbox[2] - face.bbox[0]) / width),
                box_height=float((face.bbox[3] - face.bbox[1]) / height)
            )
            db.add(face_row)
            used_person_ids.append(matched_person.id)

        if used_person_ids:
            first_person = db.query(Person).filter(Person.id == used_person_ids[0]).first()
            db_file.person_name = first_person.name if first_person else None

            db.commit()
        else:
            db_file.person_name = None

    except Exception as e:
        print(f"InsightFace tagging failed for {db_file.path}: {e}")
        _safe_rollback(db)
        db_file.person_name = None


def _tag_faces_facenet(db: Session, db_file: File, image, np, SIM_THRESHOLD: float):
    try:
        boxes, probs = mtcnn.detect(image)
        if boxes is None:
            db_file.person_name = None
            return

        face_tensors = mtcnn.extract(image, boxes, None)
        if face_tensors is None:
            db_file.person_name = None
            return

        if isinstance(face_tensors, list):
            if not face_tensors:
                db_file.person_name = None
                return
            face_batch = torch.stack(face_tensors).to(device)
        elif isinstance(face_tensors, torch.Tensor):
            face_batch = face_tensors.unsqueeze(0).to(device) if face_tensors.ndim == 3 else face_tensors.to(device)
        else:
            db_file.person_name = None
            return

        with torch.no_grad():
            embeddings = resnet(face_batch)
            embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
            embeddings_np = embeddings.cpu().numpy()

        persons = db.query(Person).all()
        used_person_ids = []

        width, height = image.size

        for i, emb in enumerate(embeddings_np):
            best_sim = -1.0
            best_person = None
            for person in persons:
                # Avoid double-tagging the same person in one photo
                if person.id in used_person_ids:
                    continue
                sim = best_similarity(person, emb)
                if sim > best_sim:
                    best_sim = sim
                    best_person = person

            if best_sim >= SIM_THRESHOLD and best_person is not None:
                matched_person = best_person
                update_person_encoding(matched_person, emb)
                db.add(matched_person)
            else:
                matched_person = _create_new_person(db, emb)
                if matched_person is None:
                    continue
                persons.append(matched_person)

            box = boxes[i]
            face = Face(
                file_id=db_file.id, 
                person_id=matched_person.id,
                box_left=float(box[0] / width),
                box_top=float(box[1] / height),
                box_width=float((box[2] - box[0]) / width),
                box_height=float((box[3] - box[1]) / height)
            )
            db.add(face)
            used_person_ids.append(matched_person.id)
            print(f"[face-match] file={db_file.path} person_id={matched_person.id} name={matched_person.name} sim={best_sim:.4f}")

        if used_person_ids:
            first_person = db.query(Person).filter(Person.id == used_person_ids[0]).first()
            db_file.person_name = first_person.name if first_person else None

            db.commit()
        else:
            db_file.person_name = None

    except Exception as e:
        print(f"FaceNet detection failure for {db_file.path}: {e}")
        _safe_rollback(db)
        db_file.person_name = None


def _tag_faces_mediapipe(db: Session, db_file: File, image, np):
    SIM_THRESHOLD = 0.75
    try:
        mp_face_mesh = mp.solutions.face_mesh
        image_array = np.array(image)
        with mp_face_mesh.FaceMesh(
            static_image_mode=True, max_num_faces=10,
            refine_landmarks=False, min_detection_confidence=0.5
        ) as face_mesh:
            results_mesh = face_mesh.process(image_array)

            if not (results_mesh and results_mesh.multi_face_landmarks):
                db_file.person_name = None
                return

            persons = db.query(Person).all()
            used_person_ids = []

            for fl in results_mesh.multi_face_landmarks:
                encoding = []
                for lm in fl.landmark:
                    encoding.extend([lm.x, lm.y, getattr(lm, "z", 0.0)])
                embedding = np.array(encoding, dtype=np.float32)
                norm = np.linalg.norm(embedding)
                if norm > 0:
                    embedding /= norm

                best_sim = -1.0
                best_person = None
                for person in persons:
                    # Avoid double-tagging the same person in one photo
                    if person.id in used_person_ids:
                        continue
                    sim = best_similarity(person, embedding)
                    if sim > best_sim:
                        best_sim = sim
                        best_person = person

                if best_person is not None and best_sim >= SIM_THRESHOLD:
                    matched_person = best_person
                    update_person_encoding(matched_person, embedding)
                    db.add(matched_person)
                else:
                    matched_person = _create_new_person(db, embedding)
                    if matched_person is None:
                        continue
                    persons.append(matched_person)

                x_coords = [lm.x for lm in fl.landmark]
                y_coords = [lm.y for lm in fl.landmark]
                min_x, max_x = min(x_coords), max(x_coords)
                min_y, max_y = min(y_coords), max(y_coords)
                
                box_left = max(0.0, float(min_x))
                box_top = max(0.0, float(min_y))
                box_width = min(1.0 - box_left, float(max_x - min_x))
                box_height = min(1.0 - box_top, float(max_y - min_y))

                face = Face(
                    file_id=db_file.id, 
                    person_id=matched_person.id,
                    box_left=box_left,
                    box_top=box_top,
                    box_width=box_width,
                    box_height=box_height
                )
                db.add(face)
                used_person_ids.append(matched_person.id)

            if used_person_ids:
                first_person = db.query(Person).filter(Person.id == used_person_ids[0]).first()
                db_file.person_name = first_person.name if first_person else None
            else:
                db_file.person_name = None

    except Exception as e:
        print(f"MediaPipe fallback skipped for {db_file.path}: {e}")
        _safe_rollback(db)
        db_file.person_name = None


# ── Person CRUD ────────────────────────────────────────────────────────────────

def get_persons(db: Session):
    # 1. Subquery to count how many faces are in each file
    face_counts = db.query(
        Face.file_id,
        func.count(Face.id).label("total_faces")
    ).group_by(Face.file_id).subquery()

    # 2. Ranked faces per person: prioritize photos with the lowest total face count
    # This ensures avatars are single-person photos if available.
    ranked_faces = db.query(
        Face.person_id,
        Face.file_id,
        func.row_number().over(
            partition_by=Face.person_id,
            order_by=[face_counts.c.total_faces.asc(), Face.file_id.asc()]
        ).label("rn")
    ).join(face_counts, Face.file_id == face_counts.c.file_id).subquery()

    # 3. Select only the top-ranked face (lowest face count) for each person
    cover_photos = db.query(
        ranked_faces.c.person_id,
        ranked_faces.c.file_id.label("cover_photo_id")
    ).filter(ranked_faces.c.rn == 1).subquery()
    
    results = db.query(Person, cover_photos.c.cover_photo_id).outerjoin(
        cover_photos, Person.id == cover_photos.c.person_id
    ).order_by(Person.id).all()
    
    # Map results back to Person objects with dynamically added cover_photo_id
    output = []
    for person, cover_id in results:
        person.cover_photo_id = cover_id
        output.append(person)
    return output


def rename_person(db: Session, person_id: int, new_name: str):
    if not new_name or not new_name.strip():
        return None
    
    new_name = new_name.strip()
    person = db.query(Person).filter(Person.id == person_id).first()
    if not person:
        return None
        
    old_name = person.name
    # Check if a person with new_name already exists
    existing_person = db.query(Person).filter(Person.name == new_name).first()
    
    if existing_person and existing_person.id != person_id:
        # MERGE logic: move all faces to the existing person
        faces = db.query(Face).filter(Face.person_id == person_id).all()
        for f in faces:
            # Prevent double-tagging the same person in one photo during merge
            duplicate = db.query(Face).filter(
                Face.file_id == f.file_id,
                Face.person_id == existing_person.id
            ).first()
            
            if duplicate:
                db.delete(f)
            else:
                f.person_id = existing_person.id
                db.add(f)
                
        # Update file metadata for ALL files referencing the old name
        if old_name:
            db.query(File).filter(File.person_name == old_name).update({"person_name": new_name})

        db.flush() # Ensure reassignments are processed
        db.delete(person)
        db.commit()
        return existing_person
    else:
        # RENAME logic: just update the name
        person.name = new_name
        db.add(person)
        
        # Update file metadata for ALL files referencing the old name
        if old_name:
            db.query(File).filter(File.person_name == old_name).update({"person_name": new_name})
                
        db.commit()
        db.refresh(person)
        return person


def merge_persons(db: Session, source_id: int, target_id: int):
    source = db.query(Person).filter(Person.id == source_id).first()
    target = db.query(Person).filter(Person.id == target_id).first()
    if not source or not target:
        return None

    source_name = source.name
    target_name = target.name

    # Reassign faces from source to target with duplicate protection
    faces = db.query(Face).filter(Face.person_id == source_id).all()
    for f in faces:
        duplicate = db.query(Face).filter(
            Face.file_id == f.file_id,
            Face.person_id == target_id
        ).first()
        
        if duplicate:
            db.delete(f)
        else:
            f.person_id = target_id
            db.add(f)
            
    # Update file metadata for ALL files referencing the old name
    if source_name:
        db.query(File).filter(File.person_name == source_name).update({"person_name": target_name})

    # Merge encodings if available
    try:
        import json
        src_samples = json.loads(source.sample_encodings or "[]")
        tgt_samples = json.loads(target.sample_encodings or "[]")
        target.sample_encodings = json.dumps((tgt_samples + src_samples)[-10:])
        db.add(target)
    except Exception:
        pass

    db.flush() # Ensure reassignments are processed
    db.delete(source)
    db.commit()
    db.refresh(target)
    return target



def delete_person(db: Session, person_id: int):
    person = db.query(Person).filter(Person.id == person_id).first()
    if not person:
        return None
    
    # Delete all faces associated with this person
    db.query(Face).filter(Face.person_id == person_id).delete()
    
    # Delete the person
    db.delete(person)
    db.commit()

    # Reset person ID counter if database is empty
    if db.query(Person).count() == 0:
        from sqlalchemy import text
        try:
            db.execute(text("DELETE FROM sqlite_sequence WHERE name='persons'"))
            db.commit()
        except Exception:
            pass

    return True


def get_person_photos(db: Session, person_id: int):
    face_rows = db.query(Face).filter(Face.person_id == person_id).all()
    file_ids = list({f.file_id for f in face_rows})
    if not file_ids:
        return []
    return db.query(File).filter(File.id.in_(file_ids)).order_by(File.path).all()


def auto_merge_unknown_persons(db: Session, sim_threshold: float = 0.60):
    """
    Compare all unnamed 'Person N' records against named people.
    If the best face similarity meets the threshold, merge the unknown
    person into the named one. Returns a summary dict.
    """
    # All named persons (whose name does NOT start with "Person ")
    named_persons = db.query(Person).filter(
        Person.name != None,
        Person.encoding != None,
    ).all()
    named_persons = [p for p in named_persons if not p.name.startswith("Person ")]

    # All unnamed persons (name starts with "Person ")
    unknown_persons = db.query(Person).filter(
        Person.name != None,
        Person.encoding != None,
    ).all()
    unknown_persons = [p for p in unknown_persons if p.name.startswith("Person ")]

    if not named_persons or not unknown_persons:
        return {"merged": 0, "checked": len(unknown_persons), "skipped": len(unknown_persons)}

    # Pre-load named embeddings for speed
    named_embeddings = []
    for np_person in named_persons:
        try:
            enc = np.array(json.loads(np_person.encoding), dtype=np.float32)
            samples = []
            if np_person.sample_encodings:
                samples = [np.array(s, dtype=np.float32) for s in json.loads(np_person.sample_encodings)[:5]]
            named_embeddings.append((np_person, enc, samples))
        except Exception:
            continue

    merged = 0
    skipped = 0

    for unknown in unknown_persons:
        try:
            unk_enc = np.array(json.loads(unknown.encoding), dtype=np.float32)
            unk_samples = []
            if unknown.sample_encodings:
                unk_samples = [np.array(s, dtype=np.float32) for s in json.loads(unknown.sample_encodings)[:5]]
            all_unk_embs = [unk_enc] + unk_samples
        except Exception:
            skipped += 1
            continue

        best_sim = -1.0
        best_target = None

        for named_person, named_enc, named_samples in named_embeddings:
            all_named_embs = [named_enc] + named_samples
            # Compare every pair and take the best score
            for u_emb in all_unk_embs:
                for n_emb in all_named_embs:
                    if u_emb.shape != n_emb.shape:
                        continue
                    denom = float(np.linalg.norm(u_emb)) * float(np.linalg.norm(n_emb))
                    if denom <= 0:
                        continue
                    sim = float(np.dot(u_emb, n_emb) / denom)
                    if sim > best_sim:
                        best_sim = sim
                        best_target = named_person

        print(f"[auto-merge] {unknown.name} → best match: {best_target.name if best_target else 'none'} (sim={best_sim:.4f})")

        if best_target and best_sim >= sim_threshold:
            # Re-fetch fresh objects to avoid stale state
            fresh_unknown = db.query(Person).filter(Person.id == unknown.id).first()
            fresh_target = db.query(Person).filter(Person.id == best_target.id).first()
            if fresh_unknown and fresh_target:
                merge_persons(db, source_id=fresh_unknown.id, target_id=fresh_target.id)
                # Update named_embeddings entry for target in case it was updated
                for i, (np_p, enc, smp) in enumerate(named_embeddings):
                    if np_p.id == fresh_target.id:
                        updated = db.query(Person).filter(Person.id == fresh_target.id).first()
                        if updated and updated.encoding:
                            try:
                                new_enc = np.array(json.loads(updated.encoding), dtype=np.float32)
                                new_smp = [np.array(s, dtype=np.float32) for s in json.loads(updated.sample_encodings or "[]")[:5]]
                                named_embeddings[i] = (updated, new_enc, new_smp)
                            except Exception:
                                pass
                        break
                merged += 1
        else:
            skipped += 1

    return {"merged": merged, "checked": len(unknown_persons), "skipped": skipped}



# ── Folder / scan ──────────────────────────────────────────────────────────────

def get_scan_folder(db: Session):
    """Return the first configured folder (legacy)."""
    return db.query(FolderConfig).order_by(FolderConfig.id).first()


def get_scan_folders(db: Session):
    """Return ALL configured folders ordered by id."""
    return db.query(FolderConfig).order_by(FolderConfig.id).all()


def add_scan_folder(db: Session, folder_path: str):
    """Add a new folder. Does NOT replace existing ones."""
    folder_path = resolve_folder_path(folder_path)

    # Check if this exact path already exists
    existing = db.query(FolderConfig).filter(FolderConfig.path == folder_path).first()
    if existing:
        return existing  # already exists, return it

    # Create new folder config
    new_folder = FolderConfig(path=folder_path)
    db.add(new_folder)
    db.commit()
    db.refresh(new_folder)
    return new_folder


def delete_scan_folder(db: Session, folder_id: int):
    folder = db.query(FolderConfig).filter(FolderConfig.id == folder_id).first()
    if not folder:
        return False

    folder_path = os.path.normpath(folder.path).lower() + os.sep

    try:
        all_files = db.query(File).all()

        files_to_delete = [
            f for f in all_files
            if os.path.normpath(f.path).lower().startswith(folder_path)
        ]

        file_ids = [f.id for f in files_to_delete]

        print(f"[delete_folder] deleting {len(file_ids)} files")

        if file_ids:
            db.query(Face).filter(Face.file_id.in_(file_ids)).delete(synchronize_session=False)
            db.query(File).filter(File.id.in_(file_ids)).delete(synchronize_session=False)

        db.delete(folder)

        db.commit()

        # ✅ SAFE cleanup (separate transaction)
        try:
            cleanup_orphaned_persons(db)
        except Exception as e:
            print("cleanup warning:", e)

        return True

    except Exception as e:
        print("[delete_folder ERROR]:", e)
        db.rollback()
        return False   # ✅ NEVER crash


def set_scan_folder(db: Session, folder_path: str):
    """Upsert a single folder (legacy behaviour — updates the first row)."""
    folder_path = resolve_folder_path(folder_path)
    folder_config = get_scan_folder(db)
    if folder_config:
        folder_config.path = folder_path
    else:
        folder_config = FolderConfig(path=folder_path)
        db.add(folder_config)
    db.commit()
    db.refresh(folder_config)
    return folder_config


# ── File CRUD ──────────────────────────────────────────────────────────────────

def create_file(db: Session, file: FileCreate):
    db_file = File(**file.dict(exclude={"auto_tag"}))
    db.add(db_file)
    try:
        db.commit()
        db.refresh(db_file)
    except IntegrityError:
        db.rollback()
        db_file = db.query(File).filter(File.path == file.path).first()

    if file.auto_tag:
        db_file = auto_tag_file(db, db_file)

    return db_file


def clear_file_person_tags(db: Session, file_id: int):
    file = db.query(File).filter(File.id == file_id).first()
    if not file:
        return None
    db.query(Face).filter(Face.file_id == file_id).delete()
    db.commit()
    db.refresh(file)
    return file


def clear_file_person_tag(db: Session, file_id: int, person_id: int):
    file = db.query(File).filter(File.id == file_id).first()
    if not file:
        return None
    face = db.query(Face).filter(Face.file_id == file_id, Face.person_id == person_id).first()
    if not face:
        return file
    db.delete(face)
    db.commit()
    
    # Check if the person is now orphaned
    face_count = db.query(Face).filter(Face.person_id == person_id).count()
    if face_count == 0:
        person = db.query(Person).filter(Person.id == person_id).first()
        if person:
            db.delete(person)
            db.commit()

    db.refresh(file)
    return file


def update_file(db: Session, file_id: int, updates: FileUpdate):
    db_file = db.query(File).filter(File.id == file_id).first()
    if not db_file:
        return None
    for key, value in updates.dict(exclude_unset=True).items():
        setattr(db_file, key, value)
    db.commit()
    db.refresh(db_file)
    db.refresh(db_file)
    return db_file


def update_face_person_tag(db: Session, face_id: int, person_id: Optional[int] = None, person_name: Optional[str] = None):
    face = db.query(Face).filter(Face.id == face_id).first()
    if not face:
        return None

    person = None
    if person_id is not None:
        person = db.query(Person).filter(Person.id == person_id).first()
        if not person:
            return None

    if person is None and person_name:
        person = db.query(Person).filter(Person.name == person_name).first()
        if person is None:
            person = Person(name=person_name, color=choose_person_color(db))
            db.add(person)
            db.commit()
            db.refresh(person)

    if person is None:
        return None

    old_person_id = face.person_id
    face.person_id = person.id
    db.commit()
    db.refresh(face)

    # If the face was moved to a different person, check if the old person is now empty
    if old_person_id and old_person_id != person.id:
        face_count = db.query(Face).filter(Face.person_id == old_person_id).count()
        if face_count == 0:
            old_person = db.query(Person).filter(Person.id == old_person_id).first()
            if old_person:
                db.delete(old_person)
                db.commit()

    file = db.query(File).filter(File.id == face.file_id).first()
    if file:
        file.person_name = person.name
        db.add(file)
        db.commit()
        db.refresh(file)

    return file


def add_file_person_tag(db: Session, file_id: int, person_id: Optional[int] = None,
                        person_name: Optional[str] = None):
    file = db.query(File).filter(File.id == file_id).first()
    if not file:
        return None

    person = None
    if person_id is not None:
        person = db.query(Person).filter(Person.id == person_id).first()
        if not person:
            return None

    if person is None and person_name:
        person = db.query(Person).filter(Person.name == person_name).first()
        if person is None:
            person = Person(name=person_name, color=choose_person_color(db))
            db.add(person)
            db.commit()
            db.refresh(person)

    if person is None:
        return None

    existing = db.query(Face).filter(Face.file_id == file_id, Face.person_id == person.id).first()
    if not existing:
        face_row = Face(file_id=file_id, person_id=person.id)
        db.add(face_row)

    file.person_name = person.name
    db.add(file)
    try:
        db.commit()
    except Exception:
        _safe_rollback(db)
    db.refresh(file)
    return file


def get_file_by_id(db: Session, file_id: int):
    return db.query(File).filter(File.id == file_id).first()


def get_file_by_path(db: Session, path: str):
    if not path:
        return None
    return db.query(File).filter(File.path == path).first()


def get_files(
    db: Session, 
    folder_paths: Optional[List[str]] = None,
    folder_path: Optional[str] = None, 
    skip: int = 0, 
    limit: int = 100,
    category: str = None,
    scenario: str = None,
    person_id: int = None,
    album: str = None
):
    """
    Returns a tuple (items, total_count) of files.
    Applies filters natively via SQLAlchemy for efficient server-side pagination.
    """
    query = db.query(File)
    
    if category:
        query = query.filter(File.category.ilike(category))
    if scenario:
        query = query.filter(File.scenario.ilike(scenario))
    if person_id:
        query = query.join(Face).filter(Face.person_id == person_id).distinct()
        
    if album:
        # Normalize path separators: replace backslash with forward slash in the DB value
        normalized_path = func.replace(File.path, '\\', '/')
        query = query.filter(
            or_(
                normalized_path.ilike(f"%/{album}/%"),
                normalized_path.ilike(f"%/{album}")
            )
        )



    prefixes = []
    if folder_paths:
        for p in folder_paths:
            prefixes.append(os.path.normpath(resolve_folder_path(p)).lower() + os.sep)
    elif folder_path:
        prefixes.append(os.path.normpath(resolve_folder_path(folder_path)).lower() + os.sep)

    if prefixes:
        conditions = []
        for pfx in prefixes:
            # Use LIKE with a more robust prefix match
            # We normalize the prefix to use the same slashes as stored in the DB if possible
            conditions.append(File.path.ilike(pfx + "%"))
        query = query.filter(or_(*conditions))

    total = query.count()
    items = query.order_by(File.path).offset(skip).limit(limit).all()
    
    return items, total

def get_filter_metadata(db: Session):
    categories = [r[0] for r in db.query(File.category).distinct().filter(File.category != None).all()]
    scenarios = [r[0] for r in db.query(File.scenario).distinct().filter(File.scenario != None).all()]
    
    paths = [r[0] for r in db.query(File.path).distinct().all()]
    albums = set()
    for p in paths:
        parts = re.split(r'[\\/]', p)
        if len(parts) > 1:
            albums.add(parts[-2])
            
    return {
        "categories": sorted(categories),
        "scenarios": sorted(scenarios),
        "albums": sorted(list(albums))
    }


def scan_and_tag_folder(db: Session, folder_path: str, force: bool = False):
    """
    Scan a folder for images and videos, auto-tag each one.
    This function uses the provided db session, not creating its own.
    """
    from app.database import SessionLocal
    import time

    start_time = time.time()
    folder_path = resolve_folder_path(folder_path)
    print(f"[scan] Starting scan of: {folder_path}")
    supported_formats = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".mp4", ".mov", ".avi", ".mkv", ".webm"}
    results = {"total_files": 0, "tagged_files": 0, "skipped_files": 0}

    if not os.path.isdir(folder_path):
        print(f"[scan] ERROR: Folder does not exist: {folder_path}")
        return results

    file_paths = []
    for root, _, files in os.walk(folder_path):
        for filename in files:
            if os.path.splitext(filename)[1].lower() in supported_formats:
                file_paths.append(os.path.join(root, filename))
    
    print(f"[scan] Found {len(file_paths)} files to process in {folder_path}")

    to_tag = []
    last_batch_time = start_time
    
    for idx, file_path in enumerate(file_paths):
        results["total_files"] += 1
        ext = os.path.splitext(file_path)[1].lower()
        file_type = "video" if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm"} else "photo"

        try:
            existing_file = db.query(File).filter(File.path == file_path).first()

            if existing_file:
                # Skip files that have already been fully processed (all tags + face scan done)
                # For videos: just need category; for photos: need category, scenario, and face_scanned
                is_fully_processed = (
                    existing_file.category is not None and
                    (file_type == "video" or existing_file.scenario is not None) and
                    existing_file.face_scanned is True
                )
                
                if not force and is_fully_processed:
                    try:
                        generate_thumbnail(existing_file)
                    except Exception:
                        pass
                    results["skipped_files"] += 1
                    continue
                    
                db_file = existing_file
                if db_file.file_type != file_type:
                    db_file.file_type = file_type
            else:
                db_file = File(path=file_path, file_type=file_type)
                db.add(db_file)
                try:
                    db.commit()
                    db.refresh(db_file)
                except IntegrityError:
                    db.rollback()
                    db_file = db.query(File).filter(File.path == file_path).first()
                    if db_file is None:
                        results["skipped_files"] += 1
                        continue

            if force:
                db_file.category = None
                db_file.scenario = None
                db_file.person_name = None
                db_file.face_scanned = False
                db.add(db_file)
                # No commit here, let batch_auto_tag_files handle it or commit below

            if file_type == "photo":
                to_tag.append(db_file)
                if len(to_tag) >= 32: # Process in chunks of 32 to avoid massive memory usage
                    batch_auto_tag_files(db, to_tag)
                    results["tagged_files"] += len(to_tag)
                    
                    # Progress logging
                    elapsed = time.time() - last_batch_time
                    batch_per_sec = 32 / elapsed if elapsed > 0 else 0
                    progress_pct = (idx / len(file_paths)) * 100
                    print(f"[scan] Progress: {idx}/{len(file_paths)} ({progress_pct:.1f}%) | {results['tagged_files']} processed | {batch_per_sec:.1f} files/sec")
                    last_batch_time = time.time()
                    
                    to_tag = []
            else:
                if not db_file.category or force:
                    db_file.category = "video"
                db_file.face_scanned = True
                db.add(db_file)
                db.commit()
                try:
                    generate_thumbnail(db_file)
                except Exception:
                    pass
                results["tagged_files"] += 1

        except Exception as e:
            print(f"Error scheduling {file_path}: {e}")
            db.rollback()
            results["skipped_files"] += 1

    # Final batch
    if to_tag:
        batch_auto_tag_files(db, to_tag)
        results["tagged_files"] += len(to_tag)

    elapsed = time.time() - start_time
    print(f"[scan] COMPLETED: {results['total_files']} total | {results['tagged_files']} tagged | {results['skipped_files']} skipped | {elapsed:.1f}s")
    return results

def recheck_and_tag_missing(db: Session) -> dict:
    """
    Smart incremental recheck:
    - Adds new files
    - ONLY fills missing fields (no overwriting)
    - Accurate counters
    """

    from app.database import SessionLocal

    supported_formats = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".mp4", ".mov", ".avi", ".mkv", ".webm"}

    results = {
        "new_files": 0,
        "retagged_files": 0,
        "removed_files": 0,
        "skipped_files": 0,
        "errors": 0,
    }

    folder_configs = get_scan_folders(db)
    valid_folders = [fc.path for fc in folder_configs if fc.path and os.path.isdir(fc.path)]

    if not valid_folders:
        return results

    to_tag = []
    
    # PASS 1: ADD NEW FILES (Metadata only)
    for folder_path in valid_folders:
        for root, _, files_in_dir in os.walk(folder_path):
            for filename in files_in_dir:
                if os.path.splitext(filename)[1].lower() not in supported_formats:
                    continue

                file_path = os.path.join(root, filename)
                ext = os.path.splitext(file_path)[1].lower()
                file_type = "video" if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm"} else "photo"

                try:
                    existing = db.query(File).filter(File.path == file_path).first()
                    if not existing:
                        # New file
                        db_file = File(path=file_path, file_type=file_type)
                        db.add(db_file)
                        db.commit()
                        db.refresh(db_file)
                        results["new_files"] += 1
                        
                        # Pre-generate thumbnail for the new file immediately
                        generate_thumbnail(db_file)

                        if file_type == "photo":
                            to_tag.append(db_file)
                        else:
                            db_file.category = "video"
                            db_file.face_scanned = True
                            db.add(db_file)
                            db.commit()
                except Exception as e:
                    print(f"[recheck:new] Error: {file_path} → {e}")
                    db.rollback()
                    results["errors"] += 1

    # PASS 2: IDENTIFY INCOMPLETE OR MISSING FILES
    all_files = db.query(File).order_by(File.path).all()
    for f in all_files:
        if not os.path.exists(f.path):
            # File is missing from disk - remove from DB
            print(f"[recheck:cleanup] Removing missing file from DB: {f.path}")
            db.query(Face).filter(Face.file_id == f.id).delete(synchronize_session=False)
            db.delete(f)
            results["removed_files"] += 1
            continue

        if f.file_type == "video":
            continue
            
        # Ensure thumbnail exists even if file is already tagged
        generate_thumbnail(f)
            
        if not f.category or not f.scenario or not f.face_scanned:
            if f not in to_tag:
                to_tag.append(f)
        else:
            results["skipped_files"] += 1
    
    if results["removed_files"] > 0:
        db.commit()

    # PROCESS ALL TAGS IN BATCHES
    if to_tag:
        print(f"[recheck] Processing {len(to_tag)} files in batches...")
        batch_auto_tag_files(db, to_tag)
        results["retagged_files"] = len(to_tag)

    return results

def cleanup_orphaned_persons(db: Session):
    """Remove persons who no longer have any files left."""
    # Get all persons who still have at least one Face
    persons_with_faces = db.query(Person.id).join(Face).distinct().all()
    active_person_ids = {p[0] for p in persons_with_faces}

    # Find orphaned persons
    all_persons = db.query(Person.id).all()
    orphaned_ids = {p[0] for p in all_persons} - active_person_ids

    if not orphaned_ids:
        return 0

    print(f"[cleanup] Removing {len(orphaned_ids)} orphaned persons")

    # Delete faces first (required to avoid FK violation)
    db.query(Face).filter(Face.person_id.in_(orphaned_ids)).delete(synchronize_session=False)

    # Delete persons
    db.query(Person).filter(Person.id.in_(orphaned_ids)).delete(synchronize_session=False)

    db.commit()

    # Reset person ID counter if database is empty
    if db.query(Person).count() == 0:
        from sqlalchemy import text
        try:
            dialect = db.get_bind().dialect.name
            if dialect == 'sqlite':
                db.execute(text("DELETE FROM sqlite_sequence WHERE name='persons'"))
            elif dialect == 'postgresql':
                db.execute(text("ALTER SEQUENCE persons_id_seq RESTART WITH 1"))
            db.commit()
        except Exception as e:
            print(f"Failed to reset persons sequence: {e}")
            db.rollback()

    return len(orphaned_ids)
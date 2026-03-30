from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.models import File, FolderConfig, Person, Face
from app.schemas import FileCreate, FileUpdate
from sqlalchemy.exc import IntegrityError
import torch
from PIL import Image
import mediapipe as mp
import os
import re
import json
import insightface
from insightface.app import FaceAnalysis
import numpy as np
from PIL import Image
import cv2

# ── InsightFace Setup ───────────────────────────────────────────────────────
try:
    # buffalo_l is the best balanced model (recommended for personal photos)
    # You can also try 'buffalo_m' or 'buffalo_s' if memory is limited
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

try:
    import clip
except ImportError:
    from clip import clip

device = "cuda" if torch.cuda.is_available() else "cpu"
try:
    model, preprocess = clip.load("ViT-B/32", device=device)
except RuntimeError:
    device = "cpu"
    model, preprocess = clip.load("ViT-B/32", device=device)

try:
    from transformers import BlipProcessor, BlipForConditionalGeneration
    blip_processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
    blip_model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base").to(device)
    BLIP_AVAILABLE = True
except Exception as e:
    print(f"BLIP model not available: {e}")
    BLIP_AVAILABLE = False

def get_image_description(image: Image.Image) -> str:
    if not BLIP_AVAILABLE:
        return None
    try:
        inputs = blip_processor(image, return_tensors="pt").to(device)
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


try:
    from facenet_pytorch import MTCNN, InceptionResnetV1
    mtcnn = MTCNN(keep_all=True, device=device)
    resnet = InceptionResnetV1(pretrained='vggface2').eval().to(device)
    FACENET_AVAILABLE = True
except Exception as e:
    print(f"facenet-pytorch not available: {e}")
    FACENET_AVAILABLE = False


# ── Session helper ─────────────────────────────────────────────────────────────

def _safe_rollback(db: Session):
    """Roll back the session, silently ignoring any secondary errors."""
    try:
        db.rollback()
    except Exception:
        pass


# ── Embedding helpers ──────────────────────────────────────────────────────────

def best_similarity(person: Person, emb) -> float:
    import numpy as np
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
    import numpy as np
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
    """Create a new person with proper name = 'Person {id}' """
    new_person = Person(
        name="",                    # temporary
        encoding=json.dumps(emb.tolist()),
        sample_encodings=json.dumps([emb.tolist()])
    )
    db.add(new_person)
    db.flush()                      # Get the ID from DB

    # Now set the proper name
    new_person.name = f"Person {new_person.id}"
    db.flush()

    return new_person


# ── Auto-tagging ───────────────────────────────────────────────────────────────

def auto_tag_file(db: Session, db_file: File):
    file_path = db_file.path
    if not os.path.exists(file_path):
        return db_file

    try:
        image = Image.open(file_path).convert("RGB")

        # ── CLIP category ──
        category_labels = [
            "personal photo", "anime", "document", "screenshot", "object",
            "celebrity", "car", "video game", "nature", "portrait", "food", "work"
        ]
        category_tokens = clip.tokenize(category_labels).to(device)
        with torch.no_grad():
            image_features = model.encode_image(preprocess(image).unsqueeze(0).to(device))
            category_features = model.encode_text(category_tokens)
            category_logits = (image_features @ category_features.T).softmax(dim=-1)
            best_category_idx = category_logits[0].argmax().item()
            db_file.category = category_labels[best_category_idx]

        # ── BLIP description ──
        description = get_image_description(image)
        if description:
            db_file.scenario = sanitize_description(description)

               # ── Face detection / recognition ──
        try:
            import numpy as np

            # Recommended starting values:
            SIM_THRESHOLD = 0.65      # ← Higher = stricter matching (less "same person split")
            MIN_FACE_RATIO = 0.07     # ← ~7% of image dimension (good for main subjects)

            # Clear old faces
            db.query(Face).filter(Face.file_id == db_file.id).delete(synchronize_session=False)

            if INSIGHTFACE_AVAILABLE:
                _tag_faces_insightface(db, db_file, image, np, SIM_THRESHOLD, MIN_FACE_RATIO)
            elif FACENET_AVAILABLE:
                _tag_faces_facenet(...)   # keep as fallback if you want
            else:
                _tag_faces_mediapipe(...) 

        except Exception as face_e:
            print(f"Face detection skipped for {file_path}: {face_e}")
            _safe_rollback(db)
            db_file.person_name = None

        try:
            db.commit()
            db.refresh(db_file)
        except Exception:
            _safe_rollback(db)

    except Exception as e:
        print(f"Error auto-tagging file {file_path}: {e}")
        _safe_rollback(db)

    return db_file


def _tag_faces_insightface(db: Session, db_file: File, image: Image.Image, np, 
                           SIM_THRESHOLD: float = 0.60, 
                           MIN_FACE_RATIO: float = 0.07):
    """
    InsightFace tagging with two improvements:
    - Higher similarity threshold to reduce "same person → different persons"
    - Filter small/background faces by relative size + detection confidence
    """
    if not INSIGHTFACE_AVAILABLE:
        db_file.person_name = None
        return

    try:
        img_np = np.array(image.convert("RGB"))
        height, width = img_np.shape[:2]
        min_face_area = (width * height) * (MIN_FACE_RATIO ** 2)   # e.g., 7% of image width/height

        # Get all faces
        faces = face_analyzer.get(img_np)

        if not faces or len(faces) == 0:
            db_file.person_name = None
            return

        persons = db.query(Person).all()
        used_person_ids = []
        valid_faces = []

        for face in faces:
            if face.embedding is None:
                continue

            # === Filter 1: Detection confidence ===
            if getattr(face, 'det_score', 0.0) < 0.5:   # skip low-confidence detections
                continue

            # === Filter 2: Face size (ignore tiny background faces) ===
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

        # Process only valid (main) faces
        for face in valid_faces:
            emb = face.embedding.astype(np.float32)   # already normalized by InsightFace

            best_sim = -1.0
            best_person = None

            for person in persons:
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

            face_row = Face(file_id=db_file.id, person_id=matched_person.id)
            db.add(face_row)
            used_person_ids.append(matched_person.id)

        # Set main person (first valid face)
        if used_person_ids:
            first_person = db.query(Person).filter(Person.id == used_person_ids[0]).first()
            db_file.person_name = first_person.name if first_person else None
        else:
            db_file.person_name = None

    except Exception as e:
        print(f"InsightFace tagging failed for {db_file.path}: {e}")
        _safe_rollback(db)
        db_file.person_name = None


# ── Person CRUD ────────────────────────────────────────────────────────────────

def get_persons(db: Session):
    return db.query(Person).order_by(Person.id).all()


def rename_person(db: Session, person_id: int, new_name: str):
    if not new_name or not new_name.strip():
        return None
    person = db.query(Person).filter(Person.id == person_id).first()
    if not person:
        return None
    person.name = new_name.strip()
    db.add(person)
    for f in db.query(Face).filter(Face.person_id == person_id).all():
        file = db.query(File).filter(File.id == f.file_id).first()
        if file:
            file.person_name = new_name.strip()
            db.add(file)
    db.commit()
    db.refresh(person)
    return person


def merge_persons(db: Session, source_id: int, target_id: int):
    source = db.query(Person).filter(Person.id == source_id).first()
    target = db.query(Person).filter(Person.id == target_id).first()
    if not source or not target:
        return None

    db.query(Face).filter(Face.person_id == source_id).update({"person_id": target_id})

    for file in db.query(File).filter(File.person_name == source.name).all():
        file.person_name = target.name
        db.add(file)

    try:
        import numpy as np
        src_samples = json.loads(source.sample_encodings or "[]")
        tgt_samples = json.loads(target.sample_encodings or "[]")
        target.sample_encodings = json.dumps((tgt_samples + src_samples)[-5:])
        db.add(target)
    except Exception:
        pass

    db.delete(source)
    db.commit()
    db.refresh(target)
    return target


def get_person_photos(db: Session, person_id: int):
    face_rows = db.query(Face).filter(Face.person_id == person_id).all()
    file_ids = list({f.file_id for f in face_rows})
    if not file_ids:
        return []
    return db.query(File).filter(File.id.in_(file_ids)).all()


# ── Folder / scan ──────────────────────────────────────────────────────────────

def get_scan_folder(db: Session):
    return db.query(FolderConfig).order_by(FolderConfig.id).first()


def get_scan_folders(db: Session):
    return db.query(FolderConfig).order_by(FolderConfig.id).all()


def add_scan_folder(db: Session, folder_path: str):
    folder_path = resolve_folder_path(folder_path)
    folder_config = db.query(FolderConfig).filter(FolderConfig.path == folder_path).first()
    if folder_config:
        return folder_config
    folder_config = FolderConfig(path=folder_path)
    db.add(folder_config)
    db.commit()
    db.refresh(folder_config)
    return folder_config


def delete_scan_folder(db: Session, folder_id: int):
    folder_config = db.query(FolderConfig).filter(FolderConfig.id == folder_id).first()
    if not folder_config:
        return None
    db.delete(folder_config)
    db.commit()
    return folder_config


def set_scan_folder(db: Session, folder_path: str):
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
    return db_file


def get_file_by_id(db: Session, file_id: int):
    return db.query(File).filter(File.id == file_id).first()


def get_files(db: Session, folder_path: Optional[str] = None, skip: int = 0, limit: int = 100):
    query = db.query(File)
    if folder_path:
        normalized_folder = os.path.normpath(resolve_folder_path(folder_path))
        all_files = query.all()
        matching_ids = [
            f.id for f in all_files
            if os.path.normpath(f.path).lower().startswith(normalized_folder.lower() + os.sep)
        ]
        return db.query(File).filter(File.id.in_(matching_ids)).offset(skip).limit(limit).all()
    return query.offset(skip).limit(limit).all()


def scan_and_tag_folder(db: Session, folder_path: str, force: bool = False):
    """
    Scan a folder for images and auto-tag each one.

    Each file is processed in its own fresh DB session so that a failure on
    one image cannot poison the transaction for subsequent images.

    NOTE: `db` here is only used to read folder config upstream; each file
    is processed with its own `file_db` session opened below.
    """
    from app.database import SessionLocal

    folder_path = resolve_folder_path(folder_path)
    supported_formats = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
    results = {"total_files": 0, "tagged_files": 0, "skipped_files": 0}

    if not os.path.isdir(folder_path):
        return results

    image_paths = []
    for root, _, files in os.walk(folder_path):
        for filename in files:
            if os.path.splitext(filename)[1].lower() in supported_formats:
                image_paths.append(os.path.join(root, filename))

    for file_path in image_paths:
        results["total_files"] += 1

        file_db = SessionLocal()
        try:
            existing_file = file_db.query(File).filter(File.path == file_path).first()

            if existing_file:
                if not force and existing_file.category and existing_file.scenario:
                    results["skipped_files"] += 1
                    continue
                db_file = existing_file
            else:
                db_file = File(path=file_path, file_type="photo")
                file_db.add(db_file)
                try:
                    file_db.commit()
                    file_db.refresh(db_file)
                except IntegrityError:
                    file_db.rollback()
                    db_file = file_db.query(File).filter(File.path == file_path).first()
                    if db_file is None:
                        results["skipped_files"] += 1
                        continue

            if force:
                db_file.category = None
                db_file.scenario = None
                db_file.person_name = None
                file_db.add(db_file)
                try:
                    file_db.commit()
                    file_db.refresh(db_file)
                except Exception:
                    file_db.rollback()

            # FIX: use file_db (per-file session), not the outer db session
            auto_tag_file(file_db, db_file)
            results["tagged_files"] += 1

        except Exception as e:
            print(f"Error processing {file_path}: {e}")
            _safe_rollback(file_db)
            results["skipped_files"] += 1
        finally:
            file_db.close()

    return results
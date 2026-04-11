from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import or_
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


DEFAULT_PERSON_COLORS = [
    '#e53935', '#8e24aa', '#3949ab', '#039be5', '#00897b',
    '#7cb342', '#fdd835', '#fb8c00', '#6d4c41', '#546e7a'
]


def choose_person_color(db: Session) -> str:
    used_colors = {person.color for person in db.query(Person).filter(Person.color != None).all()}
    for color in DEFAULT_PERSON_COLORS:
        if color not in used_colors:
            return color
    return DEFAULT_PERSON_COLORS[len(used_colors) % len(DEFAULT_PERSON_COLORS)]


def get_default_person_color(person_id: int) -> str:
    if person_id is None:
        return DEFAULT_PERSON_COLORS[0]
    return DEFAULT_PERSON_COLORS[person_id % len(DEFAULT_PERSON_COLORS)]


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


# ── Auto-tagging ───────────────────────────────────────────────────────────────

def auto_tag_file(
    db: Session,
    db_file: File,
    tag_category=True,
    tag_scenario=True,
    tag_faces=True
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
                    image_features = model.encode_image(
                        preprocess(image).unsqueeze(0).to(device)
                    )
                    category_features = model.encode_text(category_tokens)
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
            try:
                SIM_THRESHOLD = 0.65
                MIN_FACE_RATIO = 0.04

                # Clear existing faces if re-detecting
                db.query(Face).filter(
                    Face.file_id == db_file.id
                ).delete(synchronize_session=False)

                if INSIGHTFACE_AVAILABLE:
                    _tag_faces_insightface(
                        db, db_file, image, np, SIM_THRESHOLD, MIN_FACE_RATIO
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

        # ───────────── SAVE ─────────────
        db.commit()
        db.refresh(db_file)

    except Exception as e:
        print(f"[auto_tag ERROR] {file_path}: {e}")
        _safe_rollback(db)

    return db_file


def _tag_faces_insightface(db: Session, db_file: File, image: Image.Image, np,
                            SIM_THRESHOLD: float = 0.65,
                            MIN_FACE_RATIO: float = 0.04):
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
            if getattr(face, 'det_score', 0.0) < 0.5:
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


def delete_person(db: Session, person_id: int):
    person = db.query(Person).filter(Person.id == person_id).first()
    if not person:
        return None
    
    # Delete all faces associated with this person
    db.query(Face).filter(Face.person_id == person_id).delete()
    
    # Delete the person
    db.delete(person)
    db.commit()
    return True


def get_person_photos(db: Session, person_id: int):
    face_rows = db.query(Face).filter(Face.person_id == person_id).all()
    file_ids = list({f.file_id for f in face_rows})
    if not file_ids:
        return []
    return db.query(File).filter(File.id.in_(file_ids)).order_by(File.path).all()


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

    face.person_id = person.id
    db.commit()
    db.refresh(face)

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


def get_files(db: Session, folder_paths: Optional[List[str]] = None,
              folder_path: Optional[str] = None, skip: int = 0, limit: int = 100):
    """
    Return files under one or more folder paths with a stable ORDER BY path.

    Uses Python-side path prefix filtering to avoid SQLite LIKE escaping issues
    with Windows backslashes.  All rows are fetched once, filtered and sorted in
    Python, then offset/limit is applied — safe for galleries up to ~100k files.
    """
    # Normalise inputs into a list of lowercase absolute folder prefixes.
    # We append os.sep so that /photos does not accidentally match /photos2.
    prefixes: List[str] = []
    if folder_paths:
        for p in folder_paths:
            resolved = os.path.normpath(resolve_folder_path(p)).lower()
            prefixes.append(resolved + os.sep)
    elif folder_path:
        resolved = os.path.normpath(resolve_folder_path(folder_path)).lower()
        prefixes.append(resolved + os.sep)

    # Fetch all files ordered by path (deterministic, fixes the mismatch bug).
    all_files = db.query(File).order_by(File.path).all()

    if not prefixes:
        # No folder filter — return everything with pagination.
        return all_files[skip: skip + limit]

    # Filter in Python: safe on Windows backslashes, Linux forward-slashes, mixed.
    filtered = [
        f for f in all_files
        if any(os.path.normpath(f.path).lower().startswith(pfx) for pfx in prefixes)
    ]

    return filtered[skip: skip + limit]


def scan_and_tag_folder(db: Session, folder_path: str, force: bool = False):
    """
    Scan a folder for images and videos, auto-tag each one.
    This function uses the provided db session, not creating its own.
    """
    from app.database import SessionLocal

    folder_path = resolve_folder_path(folder_path)
    supported_formats = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".mp4", ".mov", ".avi", ".mkv", ".webm"}
    results = {"total_files": 0, "tagged_files": 0, "skipped_files": 0}

    if not os.path.isdir(folder_path):
        return results

    file_paths = []
    for root, _, files in os.walk(folder_path):
        for filename in files:
            if os.path.splitext(filename)[1].lower() in supported_formats:
                file_paths.append(os.path.join(root, filename))

    for file_path in file_paths:
        results["total_files"] += 1
        ext = os.path.splitext(file_path)[1].lower()
        file_type = "video" if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm"} else "photo"

        try:
            existing_file = db.query(File).filter(File.path == file_path).first()

            if existing_file:
                if not force and existing_file.category and existing_file.scenario:
                    results["skipped_files"] += 1
                    continue
                db_file = existing_file
                # Update file_type if it was incorrectly set
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
                db.add(db_file)
                try:
                    db.commit()
                    db.refresh(db_file)
                except Exception:
                    db.rollback()

            # Process based on file type
            if file_type == "photo":
                auto_tag_file(db, db_file)
            else:
                # For videos, just set basic info without AI processing
                if not db_file.category or force:
                    db_file.category = "video"
                # if not db_file.scenario or force:
                #     db_file.scenario = f"Video file: {os.path.basename(file_path)}"
                db.add(db_file)
                db.commit()
            
            results["tagged_files"] += 1

        except Exception as e:
            print(f"Error processing {file_path}: {e}")
            db.rollback()
            results["skipped_files"] += 1

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
        "skipped_files": 0,
        "errors": 0,
    }

    folder_configs = get_scan_folders(db)
    valid_folders = [fc.path for fc in folder_configs if fc.path and os.path.isdir(fc.path)]

    if not valid_folders:
        return results

    # PASS 1: ADD NEW FILES
    for folder_path in valid_folders:
        for root, _, files_in_dir in os.walk(folder_path):
            for filename in files_in_dir:
                if os.path.splitext(filename)[1].lower() not in supported_formats:
                    continue

                file_path = os.path.join(root, filename)
                ext = os.path.splitext(file_path)[1].lower()
                file_type = "video" if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm"} else "photo"

                file_db = SessionLocal()
                try:
                    existing = file_db.query(File).filter(File.path == file_path).first()
                    if existing:
                        continue

                    # New file
                    db_file = File(path=file_path, file_type=file_type)
                    file_db.add(db_file)

                    try:
                        file_db.commit()
                        file_db.refresh(db_file)
                    except IntegrityError:
                        file_db.rollback()
                        continue

                    # Full tagging for new files (only images get full processing)
                    if file_type == "photo":
                        auto_tag_file(file_db, db_file)
                    else:
                        # For videos, set basic info
                        if not db_file.category:
                            db_file.category = "video"
                        # if not db_file.scenario:
                        #     db_file.scenario = f"Video file: {os.path.basename(file_path)}"
                        file_db.add(db_file)
                        file_db.commit()

                    results["new_files"] += 1

                except Exception as e:
                    print(f"[recheck:new] Error: {file_path} → {e}")
                    _safe_rollback(file_db)
                    results["errors"] += 1
                finally:
                    file_db.close()

    # PASS 2: UPDATE ONLY MISSING DATA (skip videos for face detection)
    all_files = db.query(File).order_by(File.path).all()

    for f in all_files:
        if not os.path.exists(f.path):
            continue

        # Skip face detection for videos
        if f.file_type == "video":
            results["skipped_files"] += 1
            continue

        # Check what is missing
        has_faces = db.query(Face).filter(Face.file_id == f.id).first() is not None

        needs_category = not f.category
        needs_scenario = not f.scenario
        needs_faces = not has_faces

        # Skip fully tagged files
        if not (needs_category or needs_scenario or needs_faces):
            results["skipped_files"] += 1
            continue

        file_db = SessionLocal()
        try:
            db_file = file_db.query(File).filter(File.id == f.id).first()
            if db_file is None:
                continue

            # Partial tagging ONLY where needed
            auto_tag_file(
                file_db,
                db_file,
                tag_category=needs_category,
                tag_scenario=needs_scenario,
                tag_faces=needs_faces
            )

            results["retagged_files"] += 1

        except Exception as e:
            print(f"[recheck:update] Error: {f.path} → {e}")
            _safe_rollback(file_db)
            results["errors"] += 1
        finally:
            file_db.close()

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
    return len(orphaned_ids)
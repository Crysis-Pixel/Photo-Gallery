import os
import torch
import numpy as np
import json
import time as time_module
from PIL import Image, ImageOps
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.orm import Session
from app.models import File, Face, Person
from app.core.ai import (
    model, preprocess, device, 
    get_image_description, BLIP_AVAILABLE, 
    INSIGHTFACE_AVAILABLE, face_analyzer,
    FACENET_AVAILABLE, mtcnn, resnet
)
from app.core.embeddings import best_similarity, update_person_encoding
from app.core.thumbnails import generate_thumbnail
from app.crud.person_crud import create_new_person
from app.crud.folder_crud import get_scan_folders

def sanitize_description(text: str) -> str:
    if not text: return None
    import re
    text = re.sub(r"\b(\w+)(?:\s+\1\b)+", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:250]

def batch_auto_tag_files(db: Session, db_files: list[File], tag_category=True, tag_scenario=True, tag_faces=True, batch_size=32):
    if not db_files: return
    photos = [f for f in db_files if f.file_type == "photo"]
    videos = [f for f in db_files if f.file_type == "video"]
    for v in videos:
        if tag_category and not v.category: v.category = "video"
        v.face_scanned = True
        db.add(v)
    if not photos:
        db.commit()
        return

    def load_image(file_path):
        try:
            img = Image.open(file_path)
            img = ImageOps.exif_transpose(img)
            return img.convert("RGB")
        except Exception: return None

    for i in range(0, len(photos), batch_size):
        batch = photos[i:i + batch_size]
        with ThreadPoolExecutor(max_workers=min(len(batch), 4)) as executor:
            images = list(executor.map(load_image, [f.path for f in batch]))
        valid_indices = [idx for idx, img in enumerate(images) if img is not None]
        if not valid_indices: continue
        valid_batch = [batch[idx] for idx in valid_indices]
        valid_images = [images[idx] for idx in valid_indices]
        
        if tag_category:
            try:
                labels = ["selfie", "group photo", "family photo", "birthday", "wedding", "party", "graduation", "holiday", "travel", "nature", "cityscape", "beach", "indoor", "food", "pet", "car", "screenshot", "document", "anime", "artwork", "meme"]
                import clip
                tokens = clip.tokenize(labels).to(device)
                with torch.no_grad():
                    pre = torch.stack([preprocess(img) for img in valid_images]).to(device)
                    feat = model.encode_image(pre).float()
                    feat /= feat.norm(dim=-1, keepdim=True)
                    text_feat = model.encode_text(tokens).float()
                    text_feat /= text_feat.norm(dim=-1, keepdim=True)
                    logits = (feat @ text_feat.T).softmax(dim=-1)
                    for idx, f in enumerate(valid_batch):
                        if not f.category: f.category = labels[logits[idx].argmax().item()]
            except Exception as e: print(f"CLIP Error: {e}")

        if tag_scenario and BLIP_AVAILABLE:
            for f, img in zip(valid_batch, valid_images):
                if not f.scenario: f.scenario = sanitize_description(get_image_description(img))

        if tag_faces:
            if device == "cuda": torch.cuda.empty_cache()
            cached_persons = db.query(Person).all()
            for f, img in zip(valid_batch, valid_images):
                try:
                    generate_thumbnail(f)
                    if INSIGHTFACE_AVAILABLE: _tag_faces_insightface(db, f, img, np, 0.55, 0.01, 0.3, cached_persons=cached_persons)
                    elif FACENET_AVAILABLE: _tag_faces_facenet(db, f, img, np, 0.65)
                    f.face_scanned = True
                except Exception as e: print(f"Face Error: {e}")
        db.commit()

def _tag_faces_insightface(db, db_file, image, np, sim_th, min_ratio, det_th, cached_persons=None):
    w, h = image.size
    min_area = (w * h) * (min_ratio ** 2)
    faces = face_analyzer.get(np.array(image))
    if not faces: return
    persons = cached_persons if cached_persons is not None else db.query(Person).all()
    used = []
    for face in faces:
        if face.embedding is None or getattr(face, 'det_score', 0.0) < det_th: continue
        bbox = face.bbox.astype(int)
        if (bbox[2]-bbox[0]) * (bbox[3]-bbox[1]) < min_area: continue
        emb = face.embedding.astype(np.float32)
        best_s, best_p = -1.0, None
        for p in persons:
            if p.id in used: continue
            s = best_similarity(p, emb)
            if p.name and not p.name.startswith("Person "): s += 0.05
            if s > best_s: best_s, best_p = s, p
        if best_p and best_similarity(best_p, emb) >= sim_th:
            matched = best_p
            update_person_encoding(matched, emb)
        else:
            matched = create_new_person(db, emb)
            persons.append(matched)
        db.add(Face(file_id=db_file.id, person_id=matched.id, box_left=float(face.bbox[0]/w), box_top=float(face.bbox[1]/h), box_width=float((face.bbox[2]-face.bbox[0])/w), box_height=float((face.bbox[3]-face.bbox[1])/h)))
        used.append(matched.id)
    if used:
        first = db.query(Person).filter(Person.id == used[0]).first()
        db_file.person_name = first.name if first else None

def _tag_faces_facenet(db, db_file, image, np, sim_th):
    boxes, _ = mtcnn.detect(image)
    if boxes is None: return
    face_tensors = mtcnn.extract(image, boxes, None)
    if face_tensors is None: return
    face_batch = torch.stack(face_tensors).to(device) if isinstance(face_tensors, list) else face_tensors.to(device)
    with torch.no_grad():
        embs = torch.nn.functional.normalize(resnet(face_batch), p=2, dim=1).cpu().numpy()
    persons = db.query(Person).all()
    used = []
    w, h = image.size
    for i, emb in enumerate(embs):
        best_s, best_p = -1.0, None
        for p in persons:
            if p.id in used: continue
            s = best_similarity(p, emb)
            if s > best_s: best_s, best_p = s, p
        if best_s >= sim_th and best_p:
            matched = best_p
            update_person_encoding(matched, emb)
        else:
            matched = create_new_person(db, emb)
            persons.append(matched)
        box = boxes[i]
        db.add(Face(file_id=db_file.id, person_id=matched.id, box_left=float(box[0]/w), box_top=float(box[1]/h), box_width=float((box[2]-box[0])/w), box_height=float((box[3]-box[1])/h)))
        used.append(matched.id)

def scan_and_tag_folder_service(db: Session, folder_path: str, force: bool = False):
    supported = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".mp4", ".mov", ".avi", ".mkv", ".webm"}
    file_paths = []
    for root, _, files in os.walk(folder_path):
        for f in files:
            if os.path.splitext(f)[1].lower() in supported:
                file_paths.append(os.path.join(root, f))
    to_tag = []
    for fp in file_paths:
        ext = os.path.splitext(fp)[1].lower()
        ftype = "video" if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm"} else "photo"
        existing = db.query(File).filter(File.path == fp).first()
        if existing:
            if not force and existing.category and existing.face_scanned:
                generate_thumbnail(existing)
                continue
            f = existing
        else:
            f = File(path=fp, file_type=ftype)
            db.add(f); db.commit(); db.refresh(f)
        if ftype == "photo":
            to_tag.append(f)
            if len(to_tag) >= 32:
                batch_auto_tag_files(db, to_tag)
                to_tag = []
        else:
            f.category = "video"; f.face_scanned = True
            db.add(f); db.commit(); generate_thumbnail(f)
    if to_tag: batch_auto_tag_files(db, to_tag)

def recheck_and_tag_missing_service(db: Session):
    folders = [f.path for f in get_scan_folders(db) if f.path and os.path.isdir(f.path)]
    to_tag = []
    supported = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".mp4", ".mov", ".avi", ".mkv", ".webm"}
    for fp_dir in folders:
        for root, _, files in os.walk(fp_dir):
            for filename in files:
                if os.path.splitext(filename)[1].lower() not in supported: continue
                path = os.path.join(root, filename)
                existing = db.query(File).filter(File.path == path).first()
                if not existing:
                    ext = os.path.splitext(path)[1].lower()
                    ftype = "video" if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm"} else "photo"
                    f = File(path=path, file_type=ftype)
                    db.add(f); db.commit(); db.refresh(f)
                    generate_thumbnail(f)
                    if ftype == "photo": to_tag.append(f)
                    else: f.category = "video"; f.face_scanned = True; db.add(f); db.commit()
    all_f = db.query(File).all()
    for f in all_f:
        if not os.path.exists(f.path):
            db.query(Face).filter(Face.file_id == f.id).delete(); db.delete(f)
            continue
        generate_thumbnail(f)
        if f.file_type == "photo" and (not f.category or not f.face_scanned) and f not in to_tag: to_tag.append(f)
    db.commit()
    if to_tag: batch_auto_tag_files(db, to_tag)

def auto_tag_file_service(db: Session, db_file: File, tag_category=True, tag_scenario=True, tag_faces=True, force_faces=False):
    if not os.path.exists(db_file.path): return db_file
    if db_file.file_type == "video":
        if tag_category and not db_file.category: db_file.category = "video"
        db.commit(); return db_file
    img = Image.open(db_file.path)
    img = ImageOps.exif_transpose(img).convert("RGB")
    if tag_category:
        labels = ["selfie", "group photo", "family photo", "birthday", "wedding", "party", "graduation", "holiday", "travel", "nature", "cityscape", "beach", "indoor", "food", "pet", "car", "screenshot", "document", "anime", "artwork", "meme"]
        import clip
        tokens = clip.tokenize(labels).to(device)
        with torch.no_grad():
            feat = model.encode_image(preprocess(img).unsqueeze(0).to(device)).float()
            feat /= feat.norm(dim=-1, keepdim=True)
            text_feat = model.encode_text(tokens).float()
            text_feat /= text_feat.norm(dim=-1, keepdim=True)
            db_file.category = labels[(feat @ text_feat.T).softmax(dim=-1)[0].argmax().item()]
    if tag_scenario and BLIP_AVAILABLE:
        db_file.scenario = sanitize_description(get_image_description(img))
    if tag_faces:
        if not force_faces and db_file.category in ["anime", "meme"]: pass
        else:
            db.query(Face).filter(Face.file_id == db_file.id).delete()
            db.commit()
            if INSIGHTFACE_AVAILABLE: _tag_faces_insightface(db, db_file, img, np, 0.55, 0.01, 0.1)
            elif FACENET_AVAILABLE: _tag_faces_facenet(db, db_file, img, np, 0.55)
            db_file.face_scanned = True
    db.commit()
    # Explicitly expire and refresh to ensure relationships (like faces) are reloaded
    db.expire(db_file)
    db.refresh(db_file)
    return db_file

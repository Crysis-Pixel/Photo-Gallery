import os
import torch
import numpy as np
import json
import time as time_module
from PIL import Image, ImageOps
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.orm import Session
from app.models import File, Face, Person
import app.core.ai as _ai
from app.core.ai import get_clip, get_insightface, get_facenet, get_image_description
from app.core.embeddings import best_similarity, update_person_encoding
from app.core.thumbnails import generate_thumbnail
from app.crud.person_crud import create_new_person
from app.crud.folder_crud import get_scan_folders

import threading

_scan_lock = threading.Lock()
_active_scans = 0
_scan_total = 0
_scan_current = 0

def increment_active_scans():
    global _active_scans
    with _scan_lock:
        _active_scans += 1

def decrement_active_scans():
    global _active_scans, _scan_total, _scan_current
    with _scan_lock:
        _active_scans = max(0, _active_scans - 1)
        if _active_scans == 0:
            _scan_total = 0
            _scan_current = 0

def get_scan_status_info():
    global _active_scans, _scan_total, _scan_current
    return {
        "scan_active": _active_scans > 0,
        "total": _scan_total,
        "current": _scan_current,
        "percentage": int((_scan_current / _scan_total) * 100) if _scan_total > 0 else 0
    }

def sanitize_description(text: str) -> str:

    if not text: return None
    import re
    text = re.sub(r"\b(\w+)(?:\s+\1\b)+", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:250]

def batch_auto_tag_files(db: Session, db_files: list[File], tag_category=True, tag_scenario=True, tag_faces=True, batch_size=32):
    global _scan_current
    if not db_files: return
    photos = [f for f in db_files if f.file_type == "photo"]
    videos = [f for f in db_files if f.file_type == "video"]
    
    # Pre-increment for videos since they are processed quickly upfront
    if videos:
        with _scan_lock:
            _scan_current += len(videos)
            
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
                clip_model, preprocess, device = get_clip()
                if clip_model is not None:
                    import clip
                    tokens = clip.tokenize(labels).to(device)
                    with torch.no_grad():
                        pre = torch.stack([preprocess(img) for img in valid_images]).to(device)
                        feat = clip_model.encode_image(pre).float()
                        feat /= feat.norm(dim=-1, keepdim=True)
                        text_feat = clip_model.encode_text(tokens).float()
                        text_feat /= text_feat.norm(dim=-1, keepdim=True)
                        logits = (feat @ text_feat.T).softmax(dim=-1)
                        for idx, f in enumerate(valid_batch):
                            if not f.category: f.category = labels[logits[idx].argmax().item()]
            except Exception as e: print(f"CLIP Error: {e}")

        if tag_scenario:
            for f, img in zip(valid_batch, valid_images):
                if not f.scenario:
                    desc = get_image_description(img)  # returns None if BLIP unavailable
                    if desc: f.scenario = sanitize_description(desc)

        if tag_faces:
            _cur_device = _ai._get_device()
            if _cur_device == "cuda": torch.cuda.empty_cache()
            cached_persons = db.query(Person).all()
            for f, img in zip(valid_batch, valid_images):
                try:
                    generate_thumbnail(f)
                    if _ai.INSIGHTFACE_AVAILABLE or get_insightface() is not None:
                        _tag_faces_insightface(db, f, img, np, 0.55, 0.01, 0.3, cached_persons=cached_persons)
                        f.face_scanned = True
                    elif _ai.FACENET_AVAILABLE or get_facenet()[0] is not None:
                        _tag_faces_facenet(db, f, img, np, 0.65)
                        f.face_scanned = True
                except Exception as e:
                    import traceback
                    print(f"Face Error for {f.path}: {e}")
                    traceback.print_exc()
                    
        with _scan_lock:
            _scan_current += len(batch)
            
    db.commit()

def _tag_faces_insightface(db, db_file, image, np, sim_th, min_ratio, det_th, cached_persons=None):
    db.query(Face).filter(Face.file_id == db_file.id).delete()
    db.commit()
    face_analyzer = get_insightface()
    if face_analyzer is None: return
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
    db.query(Face).filter(Face.file_id == db_file.id).delete()
    db.commit()
    mtcnn, resnet, device = get_facenet()
    if mtcnn is None or resnet is None: return
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

def _extract_and_save_exif(db: Session, f: File):
    """Extract EXIF metadata from a file and save to DB. Skips if already populated."""
    if f.date_taken is not None:
        return  # Already done
    try:
        from app.services.exif_service import extract_exif_metadata
        from app.services.geocoding_service import reverse_geocode
        meta = extract_exif_metadata(f.path)
        changed = False
        for key in ("date_taken", "gps_latitude", "gps_longitude", "gps_altitude", "camera_make", "camera_model"):
            val = meta.get(key)
            if val is not None and getattr(f, key) is None:
                setattr(f, key, val)
                changed = True
        if meta.get("gps_latitude") and meta.get("gps_longitude") and not f.location_name:
            f.location_name = reverse_geocode(meta["gps_latitude"], meta["gps_longitude"])
            changed = True
        if changed:
            db.add(f)
    except Exception as e:
        print(f"[exif] Failed for {f.path}: {e}")


def scan_and_tag_folder_service(db: Session, folder_path: str, force: bool = False):
    increment_active_scans()
    try:
        supported_photos = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
        supported_videos = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
        supported = supported_photos | supported_videos
        
        file_paths = []
        for root, _, files in os.walk(folder_path):
            for f in files:
                if os.path.splitext(f)[1].lower() in supported:
                    file_paths.append(os.path.join(root, f))
                    
        # Group files by base name for live photo pairing
        base_to_files = {}
        for fp in file_paths:
            base, ext = os.path.splitext(fp)
            ext = ext.lower()
            if base not in base_to_files:
                base_to_files[base] = {'photo': None, 'video': None}
            if ext in supported_photos:
                base_to_files[base]['photo'] = fp
            elif ext in supported_videos:
                base_to_files[base]['video'] = fp

        to_tag = []
        
        global _scan_total, _scan_current
        with _scan_lock:
            _scan_total += len(base_to_files)
            
        for base, pair in base_to_files.items():
            with _scan_lock:
                _scan_current += 1
                
            photo_fp = pair['photo']
            video_fp = pair['video']

            video_file = None
            if video_fp:
                video_file = db.query(File).filter(File.path == video_fp).first()
                if not video_file:
                    video_file = File(path=video_fp, file_type="video")
                    db.add(video_file); db.commit(); db.refresh(video_file)
                
                # If it's part of a pair, hide it from the main gallery
                if photo_fp and not video_file.is_hidden:
                    video_file.is_hidden = True
                    db.add(video_file); db.commit()
                
                if force or not video_file.category:
                    video_file.category = "video"; video_file.face_scanned = True
                    db.add(video_file); db.commit(); generate_thumbnail(video_file)

            if photo_fp:
                photo_file = db.query(File).filter(File.path == photo_fp).first()
                if not photo_file:
                    photo_file = File(path=photo_fp, file_type="photo")
                    db.add(photo_file); db.commit(); db.refresh(photo_file)
                
                # Link the video file if present
                if video_file and photo_file.live_video_id != video_file.id:
                    photo_file.live_video_id = video_file.id
                    db.add(photo_file); db.commit()
                
                if force or not (photo_file.category and photo_file.face_scanned):
                    _extract_and_save_exif(db, photo_file)
                    to_tag.append(photo_file)
                    generate_thumbnail(photo_file)
                    
        with _scan_lock:
            _scan_total += len(to_tag)

        if to_tag: batch_auto_tag_files(db, to_tag)
        db.commit()
        # Regenerate memories after scan
        try:
            from app.services.memory_service import generate_memories
            generate_memories(db)
        except Exception as e:
            print(f"[memories] Post-scan generation error: {e}")
    finally:
        decrement_active_scans()

def recheck_and_tag_missing_service(db: Session):
    increment_active_scans()
    try:
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
        # Find files that have face_scanned but no Face records (legacy bug fix)
        face_ids = db.query(Face.file_id).distinct().all()
        files_with_faces = {row[0] for row in face_ids}
        
        global _scan_total, _scan_current
        with _scan_lock:
            _scan_total += len(all_f)
            
        for f in all_f:
            with _scan_lock:
                _scan_current += 1
                
            if not os.path.exists(f.path):
                # Delete thumbnail from disk
                from app.utils import THUMB_DIR
                thumb_path = os.path.join(THUMB_DIR, f"{f.id}.webp")
                if os.path.exists(thumb_path):
                    try:
                        os.remove(thumb_path)
                    except Exception as e:
                        print(f"Error removing thumbnail for file {f.id}: {e}")
                db.query(Face).filter(Face.file_id == f.id).delete(); db.delete(f)
                continue
            generate_thumbnail(f)
            missing_faces = f.face_scanned and f.id not in files_with_faces
            if f.file_type == "photo" and (not f.category or not f.face_scanned or missing_faces) and f not in to_tag:
                to_tag.append(f)
        db.commit()
        if to_tag:
            with _scan_lock:
                _scan_total += len(to_tag)
                
            # Extract EXIF for any newly added files before tagging
            for f in to_tag:
                _extract_and_save_exif(db, f)
                with _scan_lock:
                    _scan_current += 1
                    
            db.commit()
            
            with _scan_lock:
                _scan_total += len(to_tag)
                
            batch_auto_tag_files(db, to_tag)
        # Also extract EXIF for existing files that are missing it
        missing_exif = db.query(File).filter(
            File.file_type == "photo",
            File.date_taken.is_(None)
        ).limit(500).all()
        
        if missing_exif:
            with _scan_lock:
                _scan_total += len(missing_exif)
                
            for f in missing_exif:
                _extract_and_save_exif(db, f)
                with _scan_lock:
                    _scan_current += 1
        db.commit()
        # Regenerate memories after recheck
        try:
            from app.services.memory_service import generate_memories
            generate_memories(db)
        except Exception as e:
            print(f"[memories] Post-recheck generation error: {e}")
    finally:
        decrement_active_scans()

def auto_tag_file_service(db: Session, db_file: File, tag_category=True, tag_scenario=True, tag_faces=True, force_faces=False):
    if not os.path.exists(db_file.path): return db_file
    if db_file.file_type == "video":
        if tag_category and not db_file.category: db_file.category = "video"
        db.commit(); return db_file
    img = Image.open(db_file.path)
    img = ImageOps.exif_transpose(img).convert("RGB")
    if tag_category:
        labels = ["selfie", "group photo", "family photo", "birthday", "wedding", "party", "graduation", "holiday", "travel", "nature", "cityscape", "beach", "indoor", "food", "pet", "car", "screenshot", "document", "anime", "artwork", "meme"]
        clip_model, preprocess, device = get_clip()
        if clip_model is not None:
            import clip
            tokens = clip.tokenize(labels).to(device)
            with torch.no_grad():
                feat = clip_model.encode_image(preprocess(img).unsqueeze(0).to(device)).float()
                feat /= feat.norm(dim=-1, keepdim=True)
                text_feat = clip_model.encode_text(tokens).float()
                text_feat /= text_feat.norm(dim=-1, keepdim=True)
                db_file.category = labels[(feat @ text_feat.T).softmax(dim=-1)[0].argmax().item()]
    if tag_scenario:
        desc = get_image_description(img)  # returns None if BLIP unavailable
        if desc: db_file.scenario = sanitize_description(desc)
    if tag_faces:
        if not force_faces and db_file.category in ["anime", "meme"]: pass
        else:
            if _ai.INSIGHTFACE_AVAILABLE or get_insightface() is not None:
                _tag_faces_insightface(db, db_file, img, np, 0.55, 0.01, 0.1)
                db_file.face_scanned = True
            elif _ai.FACENET_AVAILABLE or get_facenet()[0] is not None:
                _tag_faces_facenet(db, db_file, img, np, 0.55)
                db_file.face_scanned = True
    db.commit()
    # Explicitly expire and refresh to ensure relationships (like faces) are reloaded
    db.expire(db_file)
    db.refresh(db_file)
    return db_file

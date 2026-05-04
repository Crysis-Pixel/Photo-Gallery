# app/crud/__init__.py - Facade for refactored modules
from typing import Optional, List
from sqlalchemy.orm import Session
from app.models import File, Person, Face
from app.schemas import FileCreate, FileUpdate

# Import from refactored core modules
from app.core.ai import (
    INSIGHTFACE_AVAILABLE, face_analyzer,
    BLIP_AVAILABLE, blip_processor, blip_model,
    FACENET_AVAILABLE, mtcnn, resnet,
    device, get_image_description
)
from app.core.thumbnails import generate_thumbnail

# Import from refactored CRUD sub-modules
from .file_crud import (
    get_file_by_id, get_file_by_path, create_file_record as create_file,
    update_file_record as update_file, get_files_paginated as get_files,
    get_filter_metadata
)
from .person_crud import (
    get_persons_with_covers as get_persons, 
    rename_person_record as rename_person,
    delete_person_record as delete_person,
    merge_persons_records as merge_persons,
    cleanup_orphaned_persons,
    auto_merge_unknown_persons,
    create_new_person
)
from .folder_crud import (
    get_scan_folders, add_scan_folder, delete_scan_folder
)

# Import from services
from app.services.tagging_service import (
    auto_tag_file_service as auto_tag_file,
    scan_and_tag_folder_service as scan_and_tag_folder,
    recheck_and_tag_missing_service as recheck_and_tag_missing,
    batch_auto_tag_files
)

# Utilities
from app.utils import WORKSPACE_ROOT

def resolve_folder_path(folder_path: str) -> str:
    import os
    if not folder_path: return folder_path
    if os.path.isabs(folder_path): return os.path.abspath(folder_path)
    return os.path.abspath(os.path.join(WORKSPACE_ROOT, folder_path))

def get_person_photos(db: Session, person_id: int, limit: int = 8, offset: int = 0, randomize: bool = True):
    from sqlalchemy import func
    query = db.query(File).join(Face).filter(Face.person_id == person_id)
    if randomize: query = query.order_by(func.random())
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return {"items": items, "total": total}

# Face Tagging Handlers
def add_file_person_tag(db: Session, file_id: int, person_id: Optional[int] = None, person_name: Optional[str] = None):
    db_file = get_file_by_id(db, file_id)
    if not db_file: return None
    p = None
    if person_id:
        p = db.query(Person).filter(Person.id == person_id).first()
    elif person_name:
        from .person_crud import create_new_person
        import numpy as np
        p = create_new_person(db, np.zeros(512))
        p.name = person_name
    if p:
        # Check if this person is already tagged in this file
        existing_tag = db.query(Face).filter(Face.file_id == file_id, Face.person_id == p.id).first()
        if existing_tag:
            # Already tagged, just return the file without adding duplicate
            db.refresh(db_file)
            return db_file
        
        db_file.person_name = p.name
        db.add(Face(file_id=file_id, person_id=p.id))
        db.commit(); db.refresh(db_file)
    return db_file

def clear_file_person_tag(db: Session, file_id: int, person_id: int):
    db.query(Face).filter(Face.file_id == file_id, Face.person_id == person_id).delete()
    db_file = get_file_by_id(db, file_id)
    if db_file:
        remaining = db.query(Face).filter(Face.file_id == file_id).first()
        db_file.person_name = db.query(Person).filter(Person.id == remaining.person_id).first().name if remaining else None
        db.commit(); db.refresh(db_file)
    return db_file

def update_face_person_tag(db: Session, face_id: int, person_id: Optional[int] = None, person_name: Optional[str] = None):
    face = db.query(Face).filter(Face.id == face_id).first()
    if not face: return None
    if person_id:
        face.person_id = person_id
    elif person_name:
        from .person_crud import rename_person_record
        p = rename_person_record(db, face.person_id, person_name)
    db.commit()
    return get_file_by_id(db, face.file_id)

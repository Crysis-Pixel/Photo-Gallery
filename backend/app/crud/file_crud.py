import os
import re
from typing import Optional, List
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func
from app.models import File, Face, Person
from app.schemas import FileCreate, FileUpdate

def get_file_by_id(db: Session, file_id: int):
    return db.query(File).options(joinedload(File.faces).joinedload(Face.person)).filter(File.id == file_id).first()

def get_file_by_path(db: Session, path: str):
    if not path:
        return None
    return db.query(File).filter(File.path == path).first()

def create_file_record(db: Session, file: FileCreate):
    db_file = File(**file.dict(exclude={"auto_tag"}))
    db.add(db_file)
    db.commit()
    db.refresh(db_file)
    return db_file

def update_file_record(db: Session, file_id: int, updates: FileUpdate):
    db_file = db.query(File).filter(File.id == file_id).first()
    if not db_file:
        return None
    for key, value in updates.dict(exclude_unset=True).items():
        setattr(db_file, key, value)
    db.commit()
    db.refresh(db_file)
    return db_file

def get_files_paginated(
    db: Session, 
    folder_paths: Optional[List[str]] = None,
    folder_path: Optional[str] = None, 
    skip: int = 0, 
    limit: int = 100,
    category: str = None,
    scenario: str = None,
    person_id: int = None,
    album: str = None,
    search: str = None
):
    query = db.query(File)
    
    if category:
        query = query.filter(File.category.ilike(category))
    if scenario:
        query = query.filter(File.scenario.ilike(scenario))
    if person_id:
        query = query.join(Face).filter(Face.person_id == person_id).distinct()
        
    if album:
        normalized_path = func.replace(File.path, '\\', '/')
        query = query.filter(
            or_(
                normalized_path.ilike(f"%/{album}/%"),
                normalized_path.ilike(f"%/{album}")
            )
        )

    if search:
        normalized_path = func.replace(File.path, '\\', '/')
        search_term = f"%{search}%"
        query = query.outerjoin(Face).outerjoin(Person).filter(
            or_(
                File.scenario.ilike(search_term),
                normalized_path.ilike(search_term),
                Person.name.ilike(search_term)
            )
        ).distinct()

    # Apply folder filtering if prefixes provided
    # (Simplified for now, will refine if needed)
    
    total = query.count()
    items = query.order_by(File.created_at.desc(), File.id.desc()).offset(skip).limit(limit).all()
    
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

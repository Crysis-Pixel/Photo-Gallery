import os
from sqlalchemy.orm import Session
from app.models import FolderConfig, File, Face

def get_scan_folders(db: Session):
    return db.query(FolderConfig).order_by(FolderConfig.id).all()

def add_scan_folder(db: Session, folder_path: str):
    # (Path resolution logic would go here or in a service)
    existing = db.query(FolderConfig).filter(FolderConfig.path == folder_path).first()
    if existing:
        return existing
    new_folder = FolderConfig(path=folder_path)
    db.add(new_folder)
    db.commit()
    db.refresh(new_folder)
    return new_folder

def delete_scan_folder(db: Session, folder_id: int):
    folder = db.query(FolderConfig).filter(FolderConfig.id == folder_id).first()
    if not folder:
        return False
    
    # Cascade delete logic
    folder_path = os.path.normpath(folder.path).lower() + os.sep
    all_files = db.query(File).all()
    files_to_delete = [f for f in all_files if os.path.normpath(f.path).lower().startswith(folder_path)]
    file_ids = [f.id for f in files_to_delete]
    
    if file_ids:
        db.query(Face).filter(Face.file_id.in_(file_ids)).delete(synchronize_session=False)
        db.query(File).filter(File.id.in_(file_ids)).delete(synchronize_session=False)
    
    db.delete(folder)
    db.commit()
    return True

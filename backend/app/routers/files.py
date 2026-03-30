from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app import crud, schemas
from app.database import SessionLocal
from fastapi.responses import FileResponse
import os

router = APIRouter(prefix="/files", tags=["Files"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Person endpoints ───────────────────────────────────────────────────────────
# IMPORTANT: declared BEFORE /{file_id} routes so FastAPI doesn't swallow
# "persons" as an integer path parameter (which causes a 422).

@router.get("/persons", response_model=list[schemas.PersonResponse])
def list_persons(db: Session = Depends(get_db)):
    return crud.get_persons(db)


@router.patch("/persons/{person_id}", response_model=schemas.PersonResponse)
def patch_person(person_id: int, update: schemas.PersonUpdate, db: Session = Depends(get_db)):
    if not update.name or not update.name.strip():
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    person = crud.rename_person(db, person_id, update.name.strip())
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    return person


@router.post("/persons/{person_id}/merge/{into_id}", response_model=schemas.PersonResponse)
def merge_persons(person_id: int, into_id: int, db: Session = Depends(get_db)):
    """Merge person_id into into_id — reassigns all faces, deletes the source record."""
    if person_id == into_id:
        raise HTTPException(status_code=400, detail="Cannot merge a person into themselves")
    result = crud.merge_persons(db, source_id=person_id, target_id=into_id)
    if not result:
        raise HTTPException(status_code=404, detail="One or both persons not found")
    return result


@router.get("/persons/{person_id}/photos", response_model=list[schemas.FileResponse])
def get_person_photos(person_id: int, db: Session = Depends(get_db)):
    """Return all photos that contain a detected face belonging to this person."""
    return crud.get_person_photos(db, person_id)


# ── File endpoints ─────────────────────────────────────────────────────────────

@router.post("/", response_model=schemas.FileResponse)
def create_file(file: schemas.FileCreate, db: Session = Depends(get_db)):
    return crud.create_file(db, file)


@router.post("/rescan")
def rescan_folder(
    folder_path: Optional[str] = Query(default=None),
    force: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    if folder_path:
        resolved = crud.resolve_folder_path(folder_path)
        if not os.path.isdir(resolved):
            raise HTTPException(
                status_code=400,
                detail=f"Folder does not exist on disk: {resolved}",
            )
        results = crud.scan_and_tag_folder(db, resolved, force=force)
        return {
            "message": "Folder scan completed",
            "folder": resolved,
            "total_files": results["total_files"],
            "tagged_files": results["tagged_files"],
            "skipped_files": results["skipped_files"],
        }

    folder_configs = crud.get_scan_folders(db)
    if not folder_configs:
        raise HTTPException(
            status_code=400,
            detail="No folders configured. Add a folder via POST /files/folder first.",
        )

    total_files = 0
    tagged_files = 0
    skipped_files = 0
    scanned_folders = []

    for folder_config in folder_configs:
        if not folder_config.path or not os.path.isdir(folder_config.path):
            continue
        results = crud.scan_and_tag_folder(db, folder_config.path, force=force)
        total_files += results["total_files"]
        tagged_files += results["tagged_files"]
        skipped_files += results["skipped_files"]
        scanned_folders.append(folder_config.path)

    if not scanned_folders:
        raise HTTPException(
            status_code=400,
            detail="No configured folders exist on disk.",
        )

    return {
        "message": "Folder scan completed",
        "folders": scanned_folders,
        "total_files": total_files,
        "tagged_files": tagged_files,
        "skipped_files": skipped_files,
    }


@router.get("/folder", response_model=list[schemas.FolderConfigResponse])
def list_folder_configs(db: Session = Depends(get_db)):
    return crud.get_scan_folders(db)


@router.post("/folder", response_model=schemas.FolderConfigResponse)
def add_folder_config(folder: schemas.FolderConfigCreate, db: Session = Depends(get_db)):
    if not folder.path or not folder.path.strip():
        raise HTTPException(status_code=400, detail="Folder path is required")

    folder_path = crud.resolve_folder_path(folder.path)
    if not os.path.isdir(folder_path):
        raise HTTPException(status_code=400, detail=f"Folder path does not exist: {folder_path}")

    folder_config = crud.add_scan_folder(db, folder_path)
    crud.scan_and_tag_folder(db, folder_path)
    return folder_config


@router.delete("/folder/{folder_id}")
def remove_folder_config(folder_id: int, db: Session = Depends(get_db)):
    deleted = crud.delete_scan_folder(db, folder_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Folder not found")
    return {"message": "Folder removed", "id": folder_id}


@router.patch("/{file_id}", response_model=schemas.FileResponse)
def update_file(file_id: int, updates: schemas.FileUpdate, db: Session = Depends(get_db)):
    db_file = crud.update_file(db, file_id, updates)
    if not db_file:
        raise HTTPException(status_code=404, detail="File not found")
    return db_file


@router.delete("/{file_id}/persons")
def clear_file_person_tags(file_id: int, db: Session = Depends(get_db)):
    db_file = crud.clear_file_person_tags(db, file_id)
    if not db_file:
        raise HTTPException(status_code=404, detail="File not found")
    return {"message": "Person tags cleared", "file_id": file_id}


@router.delete("/{file_id}/persons/{person_id}")
def clear_file_person_tag(file_id: int, person_id: int, db: Session = Depends(get_db)):
    db_file = crud.clear_file_person_tag(db, file_id, person_id)
    if not db_file:
        raise HTTPException(status_code=404, detail="File not found")
    return {"message": "Person tag removed", "file_id": file_id, "person_id": person_id}


@router.get("/debug-all")
def list_all_files_debug(db: Session = Depends(get_db)):
    from app.models import File
    all_files = db.query(File).all()
    folder_config = crud.get_scan_folder(db)
    return {
        "folder_config": folder_config.path if folder_config else None,
        "total_files_in_db": len(all_files),
        "sample_paths": [f.path for f in all_files[:3]],
    }


@router.get("/", response_model=list[schemas.FileResponse])
def list_files(db: Session = Depends(get_db)):
    folder_configs = crud.get_scan_folders(db)
    valid_paths = [cfg.path for cfg in folder_configs if cfg.path and os.path.isdir(cfg.path)]

    if not valid_paths:
        # No valid folders configured — return empty list rather than erroring
        return []

    files = []
    seen_ids = set()
    for path in valid_paths:
        for file in crud.get_files(db, folder_path=path):
            if file.id not in seen_ids:
                seen_ids.add(file.id)
                files.append(file)
    return files


@router.get("/{file_id}/content")
def get_file_content(file_id: int, db: Session = Depends(get_db)):
    db_file = crud.get_file_by_id(db, file_id)
    if not db_file:
        raise HTTPException(status_code=404, detail="File not found")
    if not os.path.exists(db_file.path):
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(db_file.path, filename=os.path.basename(db_file.path))
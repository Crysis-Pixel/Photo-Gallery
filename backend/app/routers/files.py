from typing import Optional, List
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
# MUST be declared BEFORE /{file_id} routes — FastAPI matches in declaration
# order, so "persons" would otherwise be swallowed as an integer file_id (422).

@router.get("/persons", response_model=List[schemas.PersonResponse])
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
    if person_id == into_id:
        raise HTTPException(status_code=400, detail="Cannot merge a person into themselves")
    result = crud.merge_persons(db, source_id=person_id, target_id=into_id)
    if not result:
        raise HTTPException(status_code=404, detail="One or both persons not found")
    return result


@router.get("/persons/{person_id}/photos", response_model=List[schemas.FileResponse])
def get_person_photos(person_id: int, db: Session = Depends(get_db)):
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
        targets = [resolved]
    else:
        folder_configs = crud.get_scan_folders(db)
        targets = [fc.path for fc in folder_configs if fc.path and os.path.isdir(fc.path)]
        if not targets:
            raise HTTPException(
                status_code=400,
                detail="No folders configured. Add a folder via POST /files/folder first.",
            )

    totals = {"total_files": 0, "tagged_files": 0, "skipped_files": 0}
    for fp in targets:
        r = crud.scan_and_tag_folder(db, fp, force=force)
        totals["total_files"] += r["total_files"]
        totals["tagged_files"] += r["tagged_files"]
        totals["skipped_files"] += r["skipped_files"]

    return {
        "message": "Folder scan completed",
        "folders": targets,
        **totals,
    }


# ── Folder config endpoints ────────────────────────────────────────────────────

@router.get("/folder", response_model=List[schemas.FolderConfigResponse])
def get_folder_configs(db: Session = Depends(get_db)):
    """Return all configured scan folders."""
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


@router.delete("/folder/{folder_id}", response_model=schemas.FolderConfigResponse)
def remove_folder_config(folder_id: int, db: Session = Depends(get_db)):
    folder_config = crud.delete_scan_folder(db, folder_id)
    if not folder_config:
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder_config


# ── File-level person tag endpoints ───────────────────────────────────────────

@router.post("/{file_id}/persons", response_model=schemas.FileResponse)
def add_person_tag(file_id: int, body: schemas.FilePersonAdd, db: Session = Depends(get_db)):
    result = crud.add_file_person_tag(
        db, file_id,
        person_id=body.person_id,
        person_name=body.person_name,
    )
    if not result:
        raise HTTPException(status_code=404, detail="File or person not found")
    return result


@router.delete("/{file_id}/persons/{person_id}", response_model=schemas.FileResponse)
def remove_person_tag(file_id: int, person_id: int, db: Session = Depends(get_db)):
    result = crud.clear_file_person_tag(db, file_id, person_id)
    if not result:
        raise HTTPException(status_code=404, detail="File not found")
    return result


# ── Generic file endpoints ─────────────────────────────────────────────────────

@router.patch("/{file_id}", response_model=schemas.FileResponse)
def update_file(file_id: int, updates: schemas.FileUpdate, db: Session = Depends(get_db)):
    db_file = crud.update_file(db, file_id, updates)
    if not db_file:
        raise HTTPException(status_code=404, detail="File not found")
    return db_file


@router.get("/debug-all")
def list_all_files_debug(db: Session = Depends(get_db)):
    from app.models import File
    all_files = db.query(File).all()
    folders = crud.get_scan_folders(db)
    return {
        "folder_configs": [f.path for f in folders],
        "total_files_in_db": len(all_files),
        "sample_paths": [f.path for f in all_files[:3]],
    }


@router.get("/", response_model=List[schemas.FileResponse])
def list_files(db: Session = Depends(get_db)):
    # Query ALL configured folders — not just the first one.
    folder_configs = crud.get_scan_folders(db)
    valid_folders = [fc.path for fc in folder_configs if fc.path and os.path.isdir(fc.path)]

    if not valid_folders:
        return []

    files = crud.get_files(db, folder_paths=valid_folders)
    if not files:
        for fp in valid_folders:
            crud.scan_and_tag_folder(db, fp)
        files = crud.get_files(db, folder_paths=valid_folders)
    return files


@router.get("/{file_id}/content")
def get_file_content(file_id: int, db: Session = Depends(get_db)):
    db_file = crud.get_file_by_id(db, file_id)
    if not db_file:
        raise HTTPException(status_code=404, detail="File not found")
    if not os.path.exists(db_file.path):
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(db_file.path, filename=os.path.basename(db_file.path))
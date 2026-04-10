from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from app import crud, schemas
from app.database import SessionLocal
from app.models import File  # ← IMPORT THIS
from fastapi.responses import FileResponse
import os
import mimetypes

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


@router.delete("/persons/{person_id}")
def delete_person(person_id: int, db: Session = Depends(get_db)):
    result = crud.delete_person(db, person_id)
    if not result:
        raise HTTPException(status_code=404, detail="Person not found")
    return {"message": "Person deleted successfully"}


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
    """Full rescan: re-tag every file in all configured folders (force=True by default)."""
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
    crud.cleanup_orphaned_persons(db)
    return {
        "message": "Folder scan completed",
        "folders": targets,
        **totals,
    }


@router.post("/recheck")
def recheck_missing(db: Session = Depends(get_db)):
    """
    Smart recheck: new files + incomplete records only.
    """
    folder_configs = crud.get_scan_folders(db)
    valid = [fc for fc in folder_configs if fc.path and os.path.isdir(fc.path)]
    if not valid:
        raise HTTPException(
            status_code=400,
            detail="No folders configured. Add a folder first."
        )

    results = crud.recheck_and_tag_missing(db)
    crud.cleanup_orphaned_persons(db)
    return {
        "message": "Recheck completed successfully",
        "new_files": results["new_files"],
        "retagged_files": results["retagged_files"],
        "errors": results["errors"],
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

    # Check if folder already exists
    existing = crud.get_scan_folders(db)
    for f in existing:
        if os.path.normpath(f.path) == os.path.normpath(folder_path):
            raise HTTPException(status_code=400, detail="Folder already added")

    folder_config = crud.add_scan_folder(db, folder_path)
    
    # Run scan in a background thread to avoid timeout
    import threading
    def scan_in_background():
        from app.database import SessionLocal
        bg_db = SessionLocal()
        try:
            crud.scan_and_tag_folder(bg_db, folder_path)
            bg_db.commit()
        except Exception as e:
            print(f"Background scan error: {e}")
            bg_db.rollback()
        finally:
            bg_db.close()
    
    thread = threading.Thread(target=scan_in_background)
    thread.daemon = True
    thread.start()
    
    return folder_config


@router.delete("/folder/{id}")
def delete_folder(id: int, db: Session = Depends(get_db)):
    success = crud.delete_scan_folder(db, id)

    if not success:
        return {"success": False, "message": "Delete failed"}

    return {"success": True}


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
def list_files(skip: int = 0, limit: int = 10000, db: Session = Depends(get_db)):
    folder_configs = crud.get_scan_folders(db)
    valid_folders = [fc.path for fc in folder_configs if fc.path and os.path.isdir(fc.path)]

    if not valid_folders:
        return []

    files = crud.get_files(db, folder_paths=valid_folders, skip=skip, limit=limit)
    if not files and skip == 0:
        for fp in valid_folders:
            crud.scan_and_tag_folder(db, fp)
        files = crud.get_files(db, folder_paths=valid_folders, skip=skip, limit=limit)
    return files


@router.get("/{file_id}/content")
def get_file_content(file_id: int, db: Session = Depends(get_db)):
    """Serve file content with proper MIME types for video streaming"""
    
    file = db.query(File).filter(File.id == file_id).first()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    
    if not os.path.exists(file.path):
        raise HTTPException(status_code=404, detail="File not found on disk")
    
    # Set proper MIME type based on file extension
    ext = os.path.splitext(file.path)[1].lower()
    media_type_map = {
        '.mp4': 'video/mp4',
        '.mov': 'video/quicktime', 
        '.avi': 'video/x-msvideo',
        '.mkv': 'video/x-matroska',
        '.webm': 'video/webm',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.bmp': 'image/bmp',
        '.webp': 'image/webp'
    }
    
    media_type = media_type_map.get(ext, 'application/octet-stream')
    
    # Return with appropriate headers for video streaming
    return FileResponse(
        file.path, 
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache",
            "Content-Disposition": f"inline; filename*=UTF-8''{os.path.basename(file.path)}"
        }
    )

@router.get("/{file_id}/stream")
async def stream_video(file_id: int, request: Request, db: Session = Depends(get_db)):
    """Stream video with range support for seeking"""
    
    file = db.query(File).filter(File.id == file_id).first()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    
    if not os.path.exists(file.path):
        raise HTTPException(status_code=404, detail="File not found on disk")
    
    file_size = os.path.getsize(file.path)
    
    # Get range header
    range_header = request.headers.get('range')
    
    if not range_header:
        # Return full file if no range requested
        return FileResponse(file.path, media_type='video/mp4')
    
    # Parse range header
    try:
        range_match = range_header.replace('bytes=', '').split('-')
        start = int(range_match[0])
        end = int(range_match[1]) if range_match[1] else file_size - 1
    except (ValueError, IndexError):
        start = 0
        end = file_size - 1
    
    # Validate range
    start = max(0, start)
    end = min(file_size - 1, end)
    
    if start > end:
        raise HTTPException(status_code=416, detail="Requested Range Not Satisfiable")
    
    chunk_size = end - start + 1
    
    # Read the requested chunk
    with open(file.path, 'rb') as f:
        f.seek(start)
        data = f.read(chunk_size)
    
    # Return partial content
    return StreamingResponse(
        iter([data]),
        status_code=206,
        media_type='video/mp4',
        headers={
            'Content-Range': f'bytes {start}-{end}/{file_size}',
            'Accept-Ranges': 'bytes',
            'Content-Length': str(chunk_size),
            'Content-Disposition': f'inline; filename="{os.path.basename(file.path)}"'
        }
    )
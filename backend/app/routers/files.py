from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from app import crud, schemas
from app.database import SessionLocal
from app.models import File
from app.utils import THUMB_DIR, THUMB_W, THUMB_H
import os
import mimetypes
from urllib.parse import quote

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


@router.post("/persons/auto-merge")
def auto_merge_persons(
    background_tasks: BackgroundTasks,
    threshold: float = Query(default=0.60, ge=0.50, le=0.95),
    db: Session = Depends(get_db),
):
    """
    Automatically merge unnamed 'Person N' records into named persons if
    their face embeddings are similar enough (controlled by `threshold`).
    Runs synchronously and returns a summary.
    """
    result = crud.auto_merge_unknown_persons(db, sim_threshold=threshold)
    return result



# ── File endpoints ─────────────────────────────────────────────────────────────

@router.post("/", response_model=schemas.FileResponse)
def create_file(file: schemas.FileCreate, db: Session = Depends(get_db)):
    return crud.create_file(db, file)


@router.post("/rescan")
def rescan_folder(
    background_tasks: BackgroundTasks,
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

    def run_bg_scan():
        bg_db = SessionLocal()
        try:
            for fp in targets:
                crud.scan_and_tag_folder(bg_db, fp, force=force)
            crud.cleanup_orphaned_persons(bg_db)
        finally:
            bg_db.close()

    background_tasks.add_task(run_bg_scan)
    
    return {
        "message": "Folder scan started in background",
        "folders": targets,
    }


@router.post("/recheck")
def recheck_missing(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
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

    def run_bg_recheck():
        bg_db = SessionLocal()
        try:
            crud.recheck_and_tag_missing(bg_db)
            crud.cleanup_orphaned_persons(bg_db)
        finally:
            bg_db.close()

    background_tasks.add_task(run_bg_recheck)

    return {
        "message": "Recheck started in background",
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


@router.patch("/faces/{face_id}", response_model=schemas.FileResponse)
def update_face(face_id: int, body: schemas.FilePersonAdd, db: Session = Depends(get_db)):
    result = crud.update_face_person_tag(
        db, face_id,
        person_id=body.person_id,
        person_name=body.person_name,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Face not found")
    return result


@router.get("/{file_id}", response_model=schemas.FileResponse)
def get_file(file_id: int, db: Session = Depends(get_db)):
    db_file = crud.get_file_by_id(db, file_id)
    if not db_file:
        raise HTTPException(status_code=404, detail="File not found")
    return db_file


# ── Generic file endpoints ─────────────────────────────────────────────────────

@router.patch("/{file_id}", response_model=schemas.FileResponse)
def update_file(file_id: int, updates: schemas.FileUpdate, db: Session = Depends(get_db)):
    db_file = crud.update_file(db, file_id, updates)
    if not db_file:
        raise HTTPException(status_code=404, detail="File not found")
    return db_file


@router.post("/{file_id}/rescan", response_model=schemas.FileResponse)
def rescan_file(file_id: int, db: Session = Depends(get_db)):
    db_file = crud.get_file_by_id(db, file_id)
    if not db_file:
        raise HTTPException(status_code=404, detail="File not found")
    
    updated_file = crud.auto_tag_file(db, db_file, tag_category=True, tag_scenario=True, tag_faces=True, force_faces=True)
    return updated_file


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


@router.get("/metadata", response_model=schemas.FilterMetadataResponse)
def get_metadata(db: Session = Depends(get_db)):
    return crud.get_filter_metadata(db)


@router.get("/", response_model=schemas.PaginatedFileResponse)
def list_files(
    background_tasks: BackgroundTasks, 
    skip: int = 0, 
    limit: int = 100, 
    category: str = None,
    scenario: str = None,
    person_id: int = None,
    album: str = None,
    db: Session = Depends(get_db)
):
    folder_configs = crud.get_scan_folders(db)
    # Use all configured folder paths, even if they aren't currently accessible
    # (e.g. external drive disconnected), so we can still see the cached metadata/thumbnails.
    target_folders = [fc.path for fc in folder_configs if fc.path]



    if not target_folders:
        return {"items": [], "total": 0}

    items, total = crud.get_files(
        db, 
        folder_paths=None, 
        skip=skip, 
        limit=limit,
        category=category,
        scenario=scenario,
        person_id=person_id,
        album=album
    )
    if not items and skip == 0 and total == 0:
        def run_bg_initial_scan():
            import traceback
            bg_db = SessionLocal()
            try:
                print("[bg_scan] Starting initial background scan...")
                # Use target_folders which we defined earlier
                for fp in target_folders:
                    crud.scan_and_tag_folder(bg_db, fp)
                crud.cleanup_orphaned_persons(bg_db)
                print("[bg_scan] Initial background scan completed.")
            except Exception as e:
                print(f"[bg_scan] CRITICAL ERROR in background scan: {e}")
                traceback.print_exc()
            finally:
                bg_db.close()
        
        background_tasks.add_task(run_bg_initial_scan)
        
    return {"items": items, "total": total}


# Move thumbnails outside the backend directory to avoid uvicorn --reload restarts
# (Constants imported from app.utils)


@router.get("/{file_id}/thumbnail")
def get_thumbnail(file_id: int, db: Session = Depends(get_db)):
    """Return a cached WebP thumbnail cropped to card proportions (cover).
    For videos, extracts a frame with OpenCV. Falls back to full image if anything fails."""
    file = db.query(File).filter(File.id == file_id).first()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    if not os.path.exists(file.path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    thumb_path = os.path.join(THUMB_DIR, f"{file_id}.webp")

    # Serve cached thumbnail immediately if it exists
    if os.path.exists(thumb_path):
        return FileResponse(thumb_path, media_type="image/webp", headers={
            "Cache-Control": "public, max-age=604800, immutable"
        })

    ext = os.path.splitext(file.path)[1].lower()
    video_exts = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}

    try:
        if ext in video_exts:
            # Extract a frame from the video using OpenCV
            import cv2
            cap = cv2.VideoCapture(file.path)
            # Read rotation metadata before seeking
            rotation = int(cap.get(cv2.CAP_PROP_ORIENTATION_META) or 0)
            # Seek to ~1 second in
            cap.set(cv2.CAP_PROP_POS_MSEC, 1000)
            ret, frame = cap.read()
            cap.release()
            if not ret:
                # Try frame 0 if 1s fails
                cap = cv2.VideoCapture(file.path)
                rotation = int(cap.get(cv2.CAP_PROP_ORIENTATION_META) or 0)
                ret, frame = cap.read()
                cap.release()
            if not ret:
                raise RuntimeError("Could not extract video frame")
            # Convert BGR -> RGB then to PIL
            from PIL import Image, ImageOps
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)
            # Apply video rotation metadata (same issue as EXIF on photos)
            if rotation == 90:
                img = img.rotate(-90, expand=True)
            elif rotation == 180:
                img = img.rotate(180, expand=True)
            elif rotation == 270:
                img = img.rotate(90, expand=True)
        else:
            from PIL import Image, ImageOps
            img = Image.open(file.path)
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")

        # Cover-crop to exact card dimensions
        from PIL import ImageOps as _io
        img = _io.fit(img, (THUMB_W, THUMB_H), method=Image.LANCZOS)
        img.save(thumb_path, "WEBP", quality=82, method=4)

        return FileResponse(thumb_path, media_type="image/webp", headers={
            "Cache-Control": "public, max-age=604800, immutable"
        })

    except Exception as e:
        print(f"Thumbnail generation failed for {file_id}: {e}")
        # Fall back to full content
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=f"/files/{file_id}/content")


@router.delete("/{file_id}/thumbnail")
def delete_thumbnail(file_id: int):
    """Invalidate the cached thumbnail (called after rescan)."""
    thumb_path = os.path.join(THUMB_DIR, f"{file_id}.webp")
    if os.path.exists(thumb_path):
        os.remove(thumb_path)
    return {"deleted": os.path.exists(thumb_path) is False}


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
    
    # Return using FastAPI's built-in FileResponse which handles headers correctly
    return FileResponse(
        file.path, 
        media_type=media_type,
        filename=os.path.basename(file.path)
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
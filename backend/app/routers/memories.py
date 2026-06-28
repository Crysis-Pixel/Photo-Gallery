"""
Memories router — /memories/ endpoints.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from app import schemas
from app.database import SessionLocal
from app.models import Memory, File, Face

router = APIRouter(prefix="/memories", tags=["Memories"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/", response_model=List[schemas.MemoryResponse])
def list_memories(
    memory_type: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Return all memories, optionally filtered by type ('location', 'album', 'time')."""
    query = db.query(Memory).order_by(Memory.start_date.desc().nullslast(), Memory.id.desc())
    if memory_type:
        query = query.filter(Memory.memory_type == memory_type)
    return query.all()


@router.get("/{memory_id}/photos", response_model=schemas.PaginatedFileResponse)
def get_memory_photos(
    memory_id: int,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """Return photos that belong to the given memory."""
    memory = db.query(Memory).filter(Memory.id == memory_id).first()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    from sqlalchemy.orm import joinedload
    from sqlalchemy import or_, func, and_

    query = db.query(File).filter(File.is_hidden.is_(False))

    if memory.memory_type == "album" and memory.album_name:
        normalized_path = func.replace(File.path, '\\', '/')
        query = query.filter(
            or_(
                normalized_path.ilike(f"%/{memory.album_name}/%"),
                normalized_path.ilike(f"%/{memory.album_name}"),
            )
        )
    elif memory.memory_type == "location":
        # Match files within the memory's date range AND near the centroid
        filters = []
        if memory.start_date and memory.end_date:
            filters.append(File.date_taken >= memory.start_date)
            filters.append(File.date_taken <= memory.end_date)
        if memory.location_name:
            filters.append(File.location_name == memory.location_name)
        elif memory.latitude and memory.longitude:
            # Fall back to GPS bounding box (~15 km)
            lat_margin = 0.14  # ~15 km
            lon_margin = 0.18
            filters.append(File.gps_latitude.between(memory.latitude - lat_margin, memory.latitude + lat_margin))
            filters.append(File.gps_longitude.between(memory.longitude - lon_margin, memory.longitude + lon_margin))
        if filters:
            query = query.filter(and_(*filters))
    else:
        # Generic time-based: use date range
        if memory.start_date and memory.end_date:
            query = query.filter(
                File.date_taken >= memory.start_date,
                File.date_taken <= memory.end_date,
            )

    total = query.count()
    items = (
        query.options(joinedload(File.faces).joinedload(Face.person))
        .order_by(File.date_taken.asc().nullslast(), File.id.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {"items": items, "total": total}


@router.post("/generate")
def generate_memories(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Trigger memory generation/refresh in the background."""
    def _run():
        from app.database import SessionLocal
        from app.services.memory_service import generate_memories as _gen
        bg_db = SessionLocal()
        try:
            result = _gen(bg_db)
            print(f"[memories] Generated: {result}")
        except Exception as e:
            print(f"[memories] Generation error: {e}")
        finally:
            bg_db.close()

    background_tasks.add_task(_run)
    return {"message": "Memory generation started"}


@router.delete("/")
def clear_memories(db: Session = Depends(get_db)):
    """Delete all memories (useful for testing / forced regeneration)."""
    db.query(Memory).delete()
    db.commit()
    return {"message": "All memories cleared"}

# ── Must run FIRST — sets HF_HOME / TORCH_HOME / CLIP_CACHE / INSIGHTFACE_HOME
# ── before any AI library is imported (HuggingFace reads env vars at import time)
import app.core.runtime_env as _runtime_env
_runtime_env.configure()

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from app.database import Base, engine, SessionLocal
from app.routers import files, models
from app.routers import memories as memories_router
from app import crud
from apscheduler.schedulers.background import BackgroundScheduler
import os

scheduler = BackgroundScheduler()


def scan_folder_task():
    """Background task to scan folder and auto-tag missing files."""
    db = SessionLocal()
    try:
        folder_configs = crud.get_scan_folders(db)
        if not folder_configs:
            print("Scan skipped: no folders configured")
            return

        scanned = False
        for folder_config in folder_configs:
            folder_path = folder_config.path
            if not folder_path or not os.path.exists(folder_path):
                print(f"Scan skipped: folder does not exist — {folder_path}")
                continue
            scanned = True
            crud.scan_and_tag_folder(db, folder_path)

        if not scanned:
            print("Scan skipped: no valid configured folders found")
    except Exception as e:
        print(f"scan_folder_task error (non-fatal): {e}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────────────────────────────
    # One-time model download (runs in background thread, no-op after first run)
    from app.core.model_downloader import ensure_models
    ensure_models()

    Base.metadata.create_all(bind=engine)

    # Auto-migrate missing columns
    inspector = inspect(engine)
    if "persons" in inspector.get_table_names():
        existing_columns = {col["name"] for col in inspector.get_columns("persons")}
        if "sample_encodings" not in existing_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE persons ADD COLUMN sample_encodings TEXT"))
        if "color" not in existing_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE persons ADD COLUMN color STRING"))
        if "cover_file_id" not in existing_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE persons ADD COLUMN cover_file_id INTEGER"))

    if "faces" in inspector.get_table_names():
        existing_columns = {col["name"] for col in inspector.get_columns("faces")}
        if "box_left" not in existing_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE faces ADD COLUMN box_left FLOAT"))
                conn.execute(text("ALTER TABLE faces ADD COLUMN box_top FLOAT"))
                conn.execute(text("ALTER TABLE faces ADD COLUMN box_width FLOAT"))
                conn.execute(text("ALTER TABLE faces ADD COLUMN box_height FLOAT"))

    if "files" in inspector.get_table_names():
        existing_columns = {col["name"] for col in inspector.get_columns("files")}
        if "face_scanned" not in existing_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE files ADD COLUMN face_scanned BOOLEAN DEFAULT FALSE"))
        # EXIF metadata columns (use PostgreSQL-compatible types)
        exif_columns = {
            "date_taken": "TIMESTAMP",
            "gps_latitude": "DOUBLE PRECISION",
            "gps_longitude": "DOUBLE PRECISION",
            "gps_altitude": "DOUBLE PRECISION",
            "camera_make": "VARCHAR",
            "camera_model": "VARCHAR",
            "location_name": "VARCHAR",
        }
        for col_name, col_type in exif_columns.items():
            if col_name not in existing_columns:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE files ADD COLUMN {col_name} {col_type}"))

        if "live_video_id" not in existing_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE files ADD COLUMN live_video_id INTEGER"))
        if "is_hidden" not in existing_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE files ADD COLUMN is_hidden BOOLEAN DEFAULT FALSE"))

    if "memories" in inspector.get_table_names():
        existing_cols = {col["name"] for col in inspector.get_columns("memories")}
        if "preview_ids" not in existing_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE memories ADD COLUMN preview_ids VARCHAR"))



    # Run periodic scan less frequently to avoid overloading the system
    scheduler.add_job(scan_folder_task, "interval", minutes=30)
    scheduler.start()

    # Generate memories on startup (in background) if none exist
    def _startup_memory_generation():
        from app.database import SessionLocal as _SL
        from app.models import Memory as _M
        from app.services.memory_service import generate_memories as _gen
        bg_db = _SL()
        try:
            count = bg_db.query(_M).count()
            if count == 0:
                print("[memories] No memories found — generating on startup...")
                result = _gen(bg_db)
                print(f"[memories] Startup generation: {result}")
        except Exception as e:
            print(f"[memories] Startup generation error: {e}")
        finally:
            bg_db.close()

    import threading
    _t = threading.Thread(target=_startup_memory_generation, daemon=True)
    _t.start()

    yield

    # ── Shutdown ───────────────────────────────────────────────────────────────
    scheduler.shutdown()


app = FastAPI(title="Photo Gallery API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi import Request

@app.middleware("http")
async def add_no_cache_header(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path.lower()
    # Prevent caching of JSON API responses, but allow caching for thumbnails, full content, and video streams
    if "thumbnail" not in path and "content" not in path and "stream" not in path:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


app.include_router(files.router)
app.include_router(models.router)
app.include_router(memories_router.router)


@app.get("/")
def root():
    return {"status": "running"}

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False
    )
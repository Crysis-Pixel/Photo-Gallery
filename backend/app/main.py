from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from app.database import Base, engine, SessionLocal
from app.routers import files
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

    import threading
    try:
        # Run the initial scan in a background thread so it doesn't block server startup
        # and allows the frontend to fetch photos immediately
        thread = threading.Thread(target=scan_folder_task, daemon=True)
        thread.start()
        print("Startup scan scheduled in the background (processing untagged files only).")
    except Exception as e:
        print(f"Startup scan failed to start: {e}")

    # Run periodic scan less frequently to avoid overloading the system
    scheduler.add_job(scan_folder_task, "interval", minutes=30)
    scheduler.start()

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

app.include_router(files.router)


@app.get("/")
def root():
    return {"status": "running"}
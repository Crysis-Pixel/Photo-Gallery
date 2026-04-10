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

    try:
        scan_folder_task()
    except Exception as e:
        print(f"Startup scan failed (app will still start): {e}")

    scheduler.add_job(scan_folder_task, "interval", minutes=5)
    scheduler.start()

    yield

    # ── Shutdown ───────────────────────────────────────────────────────────────
    scheduler.shutdown()


app = FastAPI(title="Photo Gallery API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(files.router)


@app.get("/")
def root():
    return {"status": "running"}
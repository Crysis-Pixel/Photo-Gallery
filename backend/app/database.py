from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
import os

import sys

load_dotenv()

# Determine if running in a frozen executable (production build)
IS_FROZEN = getattr(sys, 'frozen', False)

if IS_FROZEN:
    # If DATABASE_URL is explicitly provided (e.g. dev:tauri mode), honour it.
    explicit_url = os.getenv("DATABASE_URL")
    if explicit_url:
        DATABASE_URL = explicit_url
        print("Frozen build with explicit DATABASE_URL:", DATABASE_URL)
    else:
        # Production installer: use SQLite next to the executable
        install_dir = os.path.dirname(sys.executable)
        db_path = os.path.join(install_dir, "gallery.db").replace("\\", "/")
        DATABASE_URL = f"sqlite:///{db_path}"
        print("Production build: using local SQLite database at:", db_path)
else:
    # Dev mode: Use PostgreSQL
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        DATABASE_URL = "postgresql://postgres:3616@localhost:5432/photo_gallery"
        print("Warning: DATABASE_URL is not set in env — defaulting to PostgreSQL:", DATABASE_URL)
    else:
        print("Dev mode: using database from env:", DATABASE_URL)

# For SQLite, disable the same-thread check to allow access from different threads.
engine_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=30,
    pool_pre_ping=True,
    pool_timeout=60,
    **engine_kwargs
)

if DATABASE_URL.startswith("sqlite"):
    from sqlalchemy import event
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

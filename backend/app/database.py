from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# If no DATABASE_URL provided, fall back to a local SQLite file for development.
if not DATABASE_URL:
    default_sqlite = "sqlite:///./gallery.db"
    print("Warning: DATABASE_URL is not set — falling back to sqlite:", default_sqlite)
    DATABASE_URL = default_sqlite

# For SQLite, disable the same-thread check to allow access from different threads.
engine_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# ── Resolve DB path relative to THIS file (always correct, any OS) ────────
BASE_DIR = Path(__file__).resolve().parent.parent   # → C:\sideprojects\cognitive
DB_PATH  = BASE_DIR / "data" / "cognitive.db"       # → cognitive\data\cognitive.db

# ── Allow override via environment variable ────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

"""SQLite engine + session. Swap DATABASE_URL to Postgres when ready."""
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

try:
    from dotenv import load_dotenv
    # canonical config lives in the repo-root .env (two levels above app/)
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
except ImportError:
    pass  # python-dotenv is in requirements; env vars still work without it

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./airealms.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def ensure_schema():
    """Create tables + additively patch columns that older DB files lack.

    create_all() never alters existing tables, so every new nullable column
    needs an explicit ALTER here to keep live/dev databases working.
    """
    from sqlalchemy import inspect, text
    Base.metadata.create_all(bind=engine)
    cols = {c["name"] for c in inspect(engine).get_columns("monsters")}
    if "monsters" in inspect(engine).get_table_names() and "died_at" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE monsters ADD COLUMN died_at DATETIME"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

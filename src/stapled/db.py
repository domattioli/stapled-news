"""SQLite database layer with migrations."""

import sqlite3
import json
from pathlib import Path
from datetime import datetime


def connect(db_path: str) -> sqlite3.Connection:
    """Connect to database, enable WAL and foreign keys, apply migrations."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row

    _apply_migrations(conn)
    return conn


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Apply numbered SQL migrations from src/stapled/migrations/."""
    migrations_dir = Path(__file__).parent / "migrations"
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT
        )
    """
    )

    # Get applied versions
    cursor = conn.execute("SELECT version FROM schema_migrations ORDER BY version")
    applied_versions = {row[0] for row in cursor.fetchall()}

    # Find and apply pending migrations
    migration_files = sorted(migrations_dir.glob("*.sql"))
    for migration_file in migration_files:
        version = int(migration_file.stem.split("_")[0])
        if version not in applied_versions:
            sql = migration_file.read_text()
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, datetime.utcnow().isoformat()),
            )
            conn.commit()


def json_encode(obj) -> str:
    """Encode to JSON."""
    return json.dumps(obj, default=str)


def json_decode(s: str):
    """Decode from JSON."""
    return json.loads(s)


def insert_and_get_id(conn: sqlite3.Connection, sql: str, params: tuple) -> int:
    """Execute INSERT and return lastrowid."""
    cursor = conn.execute(sql, params)
    return cursor.lastrowid

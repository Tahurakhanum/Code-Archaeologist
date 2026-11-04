"""Small SQLite data-access layer; all SQL parameters are bound safely."""
import sqlite3
from pathlib import Path
from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
    repository_name TEXT NOT NULL, source_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft', summary TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS analysis_results (
    analysis_id INTEGER PRIMARY KEY,
    result_json TEXT NOT NULL,
    git_available INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS investigation_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, analysis_id INTEGER NOT NULL,
    entity_id TEXT, entity_label TEXT, question TEXT NOT NULL, answer_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
);
"""

# Columns added after the first release. init_db() adds any that an older database is missing.
ANALYSIS_COLUMNS = {"source_url": "TEXT", "progress_message": "TEXT", "error_message": "TEXT"}

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    database_path = Path(current_app.config["DATABASE"])
    database_path.parent.mkdir(parents=True, exist_ok=True)
    db = get_db()
    db.executescript(SCHEMA)
    existing_columns = {row["name"] for row in db.execute("PRAGMA table_info(analyses)")}
    for column, column_type in ANALYSIS_COLUMNS.items():
        if column not in existing_columns:
            db.execute(f"ALTER TABLE analyses ADD COLUMN {column} {column_type}")  # names come from the constant above
    # A background analysis cannot survive a server restart, so mark leftovers as failed.
    db.execute("UPDATE analyses SET status = 'failed', error_message = ? WHERE status = 'running'",
               ("The analysis was interrupted because the server stopped. Please run it again.",))
    db.commit()

def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()

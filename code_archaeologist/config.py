import os
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # The app still runs with environment variables if optional dotenv is not installed.
    pass

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "development-only-change-me")
    DATABASE = str(Path("instance") / "code_archaeologist.sqlite3")
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "25")) * 1024 * 1024
    MAX_REPOSITORY_FILES = int(os.environ.get("MAX_REPOSITORY_FILES", "5000"))
    MAX_EXTRACTED_MB = int(os.environ.get("MAX_EXTRACTED_MB", "100"))
    GIT_CLONE_DEPTH = int(os.environ.get("GIT_CLONE_DEPTH", "300"))
    REPOSITORY_STORAGE = str(Path("instance") / "repositories")
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    # Tests set this to True so analyses finish inside the request instead of a background thread.
    ANALYSIS_INLINE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

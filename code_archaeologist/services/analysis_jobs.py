"""Run a repository analysis in a background thread and record its progress in SQLite.

Why a thread? Cloning and scanning can take a while. Instead of keeping the browser
request open, the route saves a "running" analysis row, starts this job, and sends
the user to a progress page that polls /dashboard/<id>/status.

The job never executes repository code; it only clones/reads files and Git metadata.
"""
import json
import threading

from flask import current_app

from ..database import get_db
from .repository_ingestion import IngestionError, clone_public_repository, discard_repository
from .scanner import analyze_repository

UNEXPECTED_ERROR = "The analysis stopped because of an unexpected error. Try again, or try a smaller repository."


def start_analysis(analysis_id: int, job: dict) -> None:
    """Start the job. With ANALYSIS_INLINE=True (used by tests) it runs before returning."""
    app = current_app._get_current_object()
    if app.config.get("ANALYSIS_INLINE"):
        run_analysis(app, analysis_id, job)
    else:
        threading.Thread(target=run_analysis, args=(app, analysis_id, job), daemon=True,
                         name=f"analysis-{analysis_id}").start()


def run_analysis(app, analysis_id: int, job: dict) -> None:
    """Do the slow work. ``job`` holds either a GitHub URL or an already-extracted ZIP folder."""
    with app.app_context():  # gives this thread its own database connection
        root = job.get("root")
        try:
            if job["source_type"] == "github":
                set_progress(analysis_id, "Cloning the repository from GitHub…")
                root, _name, git_available = clone_public_repository(job["source_url"])
            else:
                git_available = job["git_available"]
            result = analyze_repository(root, git_available, progress=lambda message: set_progress(analysis_id, message))
            set_progress(analysis_id, "Saving results…")
            _save_result(analysis_id, result, git_available)
        except IngestionError as error:
            _fail(analysis_id, str(error))  # already a safe, user-facing message
        except Exception:
            app.logger.exception("Analysis %s failed", analysis_id)  # details go to the server log only
            _fail(analysis_id, UNEXPECTED_ERROR)
        finally:
            if root is not None:
                discard_repository(root)


def set_progress(analysis_id: int, message: str) -> None:
    db = get_db()
    db.execute("UPDATE analyses SET progress_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (message, analysis_id))
    db.commit()


def _save_result(analysis_id: int, result: dict, git_available: bool) -> None:
    db = get_db()
    if db.execute("SELECT 1 FROM analyses WHERE id = ?", (analysis_id,)).fetchone() is None:
        return  # the row disappeared while the job was running
    db.execute("INSERT OR REPLACE INTO analysis_results (analysis_id, result_json, git_available) VALUES (?, ?, ?)",
               (analysis_id, json.dumps(result), int(git_available)))
    db.execute("UPDATE analyses SET status = 'complete', summary = ?, progress_message = 'Analysis complete.', "
               "error_message = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
               (f"{result['total_files']} files analyzed", analysis_id))
    db.commit()


def _fail(analysis_id: int, message: str) -> None:
    db = get_db()
    db.execute("UPDATE analyses SET status = 'failed', error_message = ?, progress_message = NULL, "
               "updated_at = CURRENT_TIMESTAMP WHERE id = ?", (message, analysis_id))
    db.commit()

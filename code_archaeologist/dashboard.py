"""Dashboard routes: saved analyses, analysis progress, results, investigation, timeline, and reports.

Every route that touches an analysis loads it through ``_owned_analysis`` so a user
can only ever see, question, export, or delete their own analyses.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, flash, jsonify, redirect, render_template, request, send_file, session, url_for

from .auth import login_required
from .database import get_db
from .security import csrf_protect
from .services.analysis_jobs import start_analysis
from .services.explanations import explain_entity
from .services.repository_ingestion import IngestionError, extract_uploaded_archive, validate_github_url

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")

SOURCES = {"github": "GitHub", "zip": "ZIP"}
STATUSES = {"complete": "Complete", "running": "Running", "failed": "Failed"}
# Whitelisted ORDER BY clauses: user input only picks a key, never writes SQL.
SORTS = {"newest": "a.updated_at DESC, a.id DESC", "oldest": "a.created_at ASC, a.id ASC",
         "name": "a.repository_name COLLATE NOCASE ASC, a.id DESC"}
MAX_LISTED = 50
MAX_NOTES = 30


# --- Saved analyses ----------------------------------------------------------------------
@dashboard_bp.get("/")
@login_required
def index():
    filters = {
        "q": request.args.get("q", "").strip()[:100],
        "source": request.args.get("source", "") if request.args.get("source") in SOURCES else "",
        "status": request.args.get("status", "") if request.args.get("status") in STATUSES else "",
        "sort": request.args.get("sort", "newest") if request.args.get("sort") in SORTS else "newest",
    }
    where, params = ["a.user_id = ?"], [session["user_id"]]
    if filters["q"]:
        where.append("a.repository_name LIKE ? ESCAPE '\\'")
        params.append("%" + re.sub(r"([\\%_])", r"\\\1", filters["q"]) + "%")  # treat % and _ literally
    if filters["source"]:
        where.append("a.source_type = ?")
        params.append(filters["source"])
    if filters["status"]:
        where.append("a.status = ?")
        params.append(filters["status"])
    db = get_db()
    analyses = db.execute(f"SELECT a.* FROM analyses a WHERE {' AND '.join(where)} ORDER BY {SORTS[filters['sort']]} LIMIT ?",
                          (*params, MAX_LISTED + 1)).fetchall()
    counts = {row["status"]: row["total"] for row in db.execute(
        "SELECT status, COUNT(*) AS total FROM analyses WHERE user_id = ? GROUP BY status", (session["user_id"],))}
    stats = {
        "total": sum(counts.values()),
        "complete": counts.get("complete", 0),
        "running": counts.get("running", 0),
        "failed": counts.get("failed", 0),
        "repositories": db.execute("SELECT COUNT(DISTINCT repository_name) FROM analyses WHERE user_id = ? AND status = 'complete'",
                                   (session["user_id"],)).fetchone()[0],
    }
    return render_template("dashboard/index.html", analyses=analyses[:MAX_LISTED], more_results=len(analyses) > MAX_LISTED,
                           filters=filters, filtering=any([filters["q"], filters["source"], filters["status"]]),
                           stats=stats, sources=SOURCES, statuses=STATUSES)


# --- Starting an analysis and following its progress -------------------------------------
@dashboard_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_analysis():
    if request.method == "POST":
        return _new_analysis_post()
    return render_template("dashboard/new_analysis.html")


@csrf_protect
def _new_analysis_post():
    db = get_db()
    running = db.execute("SELECT id FROM analyses WHERE user_id = ? AND status = 'running' LIMIT 1", (session["user_id"],)).fetchone()
    if running is not None:
        flash("Please wait for your current analysis to finish before starting another one.", "warning")
        return redirect(url_for("dashboard.progress", analysis_id=running["id"]))

    source_type = request.form.get("source_type")
    job, source_url = {"source_type": source_type}, None
    try:
        if source_type == "github":
            source_url = request.form.get("repository_url", "").strip()
            clone_url = validate_github_url(source_url)  # quick check now; the slow clone runs in the job
            name, job["source_url"] = Path(urlparse(clone_url).path).stem, clone_url
        elif source_type == "zip":
            # The uploaded file only exists during this request, so it is safely extracted now.
            job["root"], name, job["git_available"] = extract_uploaded_archive(request.files.get("archive"))
        else:
            raise IngestionError("Choose a GitHub repository or ZIP archive.")
    except IngestionError as error:
        flash(str(error), "error")
        return render_template("dashboard/new_analysis.html"), 400

    cursor = db.execute(
        "INSERT INTO analyses (user_id, repository_name, source_type, source_url, status, progress_message) VALUES (?, ?, ?, ?, 'running', ?)",
        (session["user_id"], name, source_type, source_url, "Waiting to start…"))
    db.commit()
    start_analysis(cursor.lastrowid, job)
    return redirect(url_for("dashboard.progress", analysis_id=cursor.lastrowid))


@dashboard_bp.get("/<int:analysis_id>/progress")
@login_required
def progress(analysis_id):
    row = _owned_analysis(analysis_id, with_result=False)
    if row is None:
        return _not_found()
    if row["status"] == "complete":
        return redirect(url_for("dashboard.detail", analysis_id=analysis_id))
    return render_template("dashboard/progress.html", analysis=row)


@dashboard_bp.get("/<int:analysis_id>/status")
@login_required
def status(analysis_id):
    """Small JSON endpoint polled by the progress page."""
    row = _owned_analysis(analysis_id, with_result=False)
    if row is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"status": row["status"], "progress": row["progress_message"], "error": row["error_message"],
                    "detail_url": url_for("dashboard.detail", analysis_id=analysis_id)})


# --- Viewing results ---------------------------------------------------------------------
@dashboard_bp.get("/<int:analysis_id>")
@login_required
def detail(analysis_id):
    row, result, response = _finished_analysis(analysis_id)
    if response:
        return response
    return render_template("dashboard/detail.html", analysis=row, result=result)


@dashboard_bp.get("/<int:analysis_id>/investigate")
@login_required
def investigate(analysis_id):
    row, result, response = _finished_analysis(analysis_id)
    if response:
        return response
    entity = _find_entity(result, request.args.get("entity", ""))
    return _render_investigation(row, result, entity)


@dashboard_bp.post("/<int:analysis_id>/ask")
@login_required
@csrf_protect
def ask_question(analysis_id):
    row, result, response = _finished_analysis(analysis_id)
    if response:
        return response
    entity = _find_entity(result, request.form.get("entity_id", ""))
    if entity is None:
        flash("Select a function or class before asking a question.", "error")
        return redirect(url_for("dashboard.investigate", analysis_id=analysis_id))
    from .services.ai_explanations import answer_question
    question = request.form.get("question", "").strip()
    answer = answer_question(entity, result, question)
    _save_note(analysis_id, entity, question, answer)
    return _render_investigation(row, result, entity, answer=answer, asked_question=question)


@dashboard_bp.post("/<int:analysis_id>/ask-repository")
@login_required
@csrf_protect
def ask_repository(analysis_id):
    row, result, response = _finished_analysis(analysis_id)
    if response:
        return response
    from .services.ai_explanations import answer_repository_question
    question = request.form.get("question", "").strip()
    answer = answer_repository_question(result, question)
    _save_note(analysis_id, None, question, answer)
    return _render_investigation(row, result, None, repository_answer=answer, repository_question=question)


@dashboard_bp.post("/<int:analysis_id>/notes/<int:note_id>/delete")
@login_required
@csrf_protect
def delete_note(analysis_id, note_id):
    if _owned_analysis(analysis_id, with_result=False) is None:
        return _not_found()
    db = get_db()
    db.execute("DELETE FROM investigation_notes WHERE id = ? AND analysis_id = ?", (note_id, analysis_id))
    db.commit()
    flash("The saved answer was removed.", "success")
    return redirect(url_for("dashboard.investigate", analysis_id=analysis_id))


@dashboard_bp.get("/<int:analysis_id>/timeline")
@login_required
def timeline(analysis_id):
    row, result, response = _finished_analysis(analysis_id)
    if response:
        return response
    selected_hash = request.args.get("commit", "")
    selected = next((item for item in result.get("timeline", []) if item["hash"] == selected_hash), None)
    return render_template("dashboard/timeline.html", analysis=row, timeline=result.get("timeline", []),
                           timeline_recorded="timeline" in result, selected=selected)


@dashboard_bp.get("/<int:analysis_id>/report.pdf")
@login_required
def download_report(analysis_id):
    row, result, response = _finished_analysis(analysis_id)
    if response:
        return response
    from .services.pdf_report import build_pdf_report
    filename = re.sub(r"[^A-Za-z0-9_-]+", "-", row["repository_name"]).strip("-") or "analysis"
    return send_file(build_pdf_report(row, result, notes=_load_notes(analysis_id)[:10]), mimetype="application/pdf",
                     as_attachment=True, download_name=f"{filename}-code-archaeologist-report.pdf")


# --- Deleting ----------------------------------------------------------------------------
@dashboard_bp.get("/<int:analysis_id>/delete")
@login_required
def confirm_delete(analysis_id):
    row = _owned_analysis(analysis_id, with_result=False)
    if row is None:
        return _not_found()
    note_count = get_db().execute("SELECT COUNT(*) FROM investigation_notes WHERE analysis_id = ?", (analysis_id,)).fetchone()[0]
    return render_template("dashboard/delete_confirm.html", analysis=row, note_count=note_count)


@dashboard_bp.post("/<int:analysis_id>/delete")
@login_required
@csrf_protect
def delete(analysis_id):
    row = _owned_analysis(analysis_id, with_result=False)
    if row is None:
        return _not_found()
    if row["status"] == "running":
        flash("This analysis is still running. Delete it after it finishes.", "warning")
        return redirect(url_for("dashboard.progress", analysis_id=analysis_id))
    db = get_db()
    db.execute("DELETE FROM analyses WHERE id = ? AND user_id = ?", (analysis_id, session["user_id"]))
    db.commit()  # results and saved answers are removed by ON DELETE CASCADE
    flash(f"Deleted the analysis of “{row['repository_name']}” and its saved answers.", "success")
    return redirect(url_for("dashboard.index"))


# --- Helpers -----------------------------------------------------------------------------
def _owned_analysis(analysis_id: int, with_result: bool = True):
    """Load an analysis only if it belongs to the logged-in user (otherwise None)."""
    if with_result:
        sql = ("SELECT a.*, r.result_json, r.git_available FROM analyses a "
               "LEFT JOIN analysis_results r ON r.analysis_id = a.id WHERE a.id = ? AND a.user_id = ?")
    else:
        sql = "SELECT a.* FROM analyses a WHERE a.id = ? AND a.user_id = ?"
    return get_db().execute(sql, (analysis_id, session["user_id"])).fetchone()


def _finished_analysis(analysis_id: int):
    """Return (row, result, None) for a finished analysis, or (None, None, redirect_response)."""
    row = _owned_analysis(analysis_id)
    if row is None:
        return None, None, _not_found()
    if row["status"] != "complete" or row["result_json"] is None:
        return None, None, redirect(url_for("dashboard.progress", analysis_id=analysis_id))
    return row, json.loads(row["result_json"]), None


def _not_found():
    flash("That analysis was not found.", "error")
    return redirect(url_for("dashboard.index"))


def _find_entity(result: dict, entity_id: str):
    return next((item for item in result.get("entities", []) if item["id"] == entity_id), None)


def _render_investigation(row, result, entity, **extra):
    explanation = explain_entity(entity, result) if entity is not None else None
    return render_template("dashboard/investigate.html", analysis=row, result=result, entity=entity,
                           explanation=explanation, notes=_load_notes(row["id"]), **extra)


def _save_note(analysis_id: int, entity, question: str, answer: dict) -> None:
    """Keep each answered question so it can be reviewed later and added to the PDF report."""
    if not question:
        return
    db = get_db()
    db.execute("INSERT INTO investigation_notes (analysis_id, entity_id, entity_label, question, answer_json) VALUES (?, ?, ?, ?, ?)",
               (analysis_id, entity["id"] if entity else None,
                f"{entity['kind']} {entity.get('display_name', entity['name'])}" if entity else "Whole repository",
                question[:800], json.dumps(answer)))
    # Keep only the newest MAX_NOTES answers per analysis.
    db.execute("DELETE FROM investigation_notes WHERE analysis_id = ? AND id NOT IN "
               "(SELECT id FROM investigation_notes WHERE analysis_id = ? ORDER BY id DESC LIMIT ?)",
               (analysis_id, analysis_id, MAX_NOTES))
    db.commit()


def _load_notes(analysis_id: int) -> list[dict]:
    rows = get_db().execute("SELECT * FROM investigation_notes WHERE analysis_id = ? ORDER BY id DESC", (analysis_id,)).fetchall()
    return [{**dict(row), "answer": json.loads(row["answer_json"])} for row in rows]

"""Tests for authentication, ownership checks, ingestion validation, background analysis,
saved-analysis management, repository questions, saved answers, timeline, and PDF reports."""
import json
import shutil
import stat
import time
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest
from git import Actor, Repo

from code_archaeologist import create_app
from code_archaeologist.database import get_db
from code_archaeologist.services import analysis_jobs
from code_archaeologist.services.repository_ingestion import IngestionError, validate_github_url


# ---------- Fixtures and helpers ----------
def make_app(tmp_path, **extra):
    config = {"TESTING": True, "SECRET_KEY": "test-key", "DATABASE": str(tmp_path / "test.sqlite3"),
              "REPOSITORY_STORAGE": str(tmp_path / "repositories"), "OPENAI_API_KEY": "", "ANALYSIS_INLINE": True}
    config.update(extra)
    return create_app(config)


@pytest.fixture()
def app(tmp_path):
    return make_app(tmp_path)


def token(client):
    with client.session_transaction() as session:
        if "csrf_token" in session:
            return session["csrf_token"]
    client.get("/auth/login")  # any page with a form creates a fresh token
    with client.session_transaction() as session:
        return session["csrf_token"]


def sign_up(client, email="ada@example.com", password="safe-password"):
    client.get("/auth/signup")
    client.post("/auth/signup", data={"csrf_token": token(client), "name": "Ada", "email": email, "password": password})
    with client.session_transaction() as session:
        return session["user_id"]


def make_git_repository(root: Path) -> None:
    repository = Repo.init(root)
    start = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    sources = [
        "def total(items):\n    return sum(items)\n",
        "def total(items):\n    return sum(items)\n\ndef report(items):\n    return total(items)\n",
        "def total(items):\n    # fix rounding\n    return round(sum(items), 2)\n\ndef report(items):\n    return total(items)\n",
    ]
    for number, (author, source) in enumerate(zip(["Ada", "Grace", "Ada"], sources)):
        (root / "billing.py").write_text(source)
        (root / "web.js").write_text(f"import express from 'express';\nexport function start() {{ return {number}; }}\n")
        repository.index.add(["billing.py", "web.js"])
        when = f"{int((start + timedelta(days=number * 3)).timestamp())} +0000"
        message = "Fix rounding bug" if number == 2 else f"Change {number}"
        repository.index.commit(message, author=Actor(author, f"{author}@example.com"), committer=Actor(author, f"{author}@example.com"),
                                author_date=when, commit_date=when)


def zip_bytes(files: dict, symlink: str | None = None) -> BytesIO:
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w") as zip_file:
        for name, content in files.items():
            zip_file.writestr(name, content)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zip_file.writestr(info, "/etc/passwd")
    archive.seek(0)
    return archive


def upload_zip(client, archive, filename="sample.zip"):
    client.get("/dashboard/new")
    return client.post("/dashboard/new", data={"csrf_token": token(client), "source_type": "zip", "archive": (archive, filename)},
                       content_type="multipart/form-data")


@pytest.fixture()
def fake_clone(monkeypatch, tmp_path):
    """Replace the network clone with a local Git repository copy."""
    source = tmp_path / "source-repo"
    source.mkdir()
    make_git_repository(source)

    def clone(url):
        destination = tmp_path / "repositories" / f"clone-{time.time_ns()}"
        shutil.copytree(source, destination)
        return destination, "billing", True

    monkeypatch.setattr(analysis_jobs, "clone_public_repository", clone)
    return clone


def analyze_github(client, url="https://github.com/example/billing"):
    client.get("/dashboard/new")
    return client.post("/dashboard/new", data={"csrf_token": token(client), "source_type": "github", "repository_url": url})


@pytest.fixture()
def finished(app, fake_clone):
    client = app.test_client()
    sign_up(client)
    response = analyze_github(client)
    analysis_id = int(response.headers["Location"].split("/")[-2])
    return client, analysis_id


# ---------- Authentication ----------
def test_login_rejects_wrong_password_and_logout_ends_session(app):
    client = app.test_client()
    sign_up(client)
    client.post("/auth/logout", data={"csrf_token": token(client)})
    assert client.get("/dashboard/").status_code == 302
    client.get("/auth/login")
    response = client.post("/auth/login", data={"csrf_token": token(client), "email": "ada@example.com", "password": "wrong-password"})
    assert response.status_code == 401
    response = client.post("/auth/login", data={"csrf_token": token(client), "email": "ada@example.com", "password": "safe-password"})
    assert response.status_code == 302 and client.get("/dashboard/").status_code == 200


def test_post_without_csrf_token_is_rejected(app):
    client = app.test_client()
    sign_up(client)
    assert client.post("/dashboard/new", data={"source_type": "github", "repository_url": "https://github.com/a/b"}).status_code == 400


def test_passwords_are_hashed(app):
    client = app.test_client()
    sign_up(client)
    with app.app_context():
        stored = get_db().execute("SELECT password_hash FROM users").fetchone()[0]
    assert "safe-password" not in stored


# ---------- Ingestion validation ----------
@pytest.mark.parametrize("url", ["http://github.com/a/b", "https://gitlab.com/a/b", "https://github.com/onlyowner",
                                 "https://github.com/a/b/tree/main", "file:///etc/passwd", "https://github.com.evil.com/a/b", ""])
def test_github_url_validation_rejects_unsafe_urls(app, url):
    with app.app_context(), pytest.raises(IngestionError):
        validate_github_url(url)


def test_github_url_validation_normalizes_valid_urls(app):
    with app.app_context():
        assert validate_github_url("https://github.com/owner/repo.git") == "https://github.com/owner/repo.git"
        assert validate_github_url(" https://www.github.com/owner/repo/ ") == "https://github.com/owner/repo.git"


@pytest.mark.parametrize("bad_name", ["../evil.py", "folder/../../evil.py", "/absolute.py"])
def test_zip_path_traversal_is_rejected(app, tmp_path, bad_name):
    client = app.test_client()
    sign_up(client)
    response = upload_zip(client, zip_bytes({"ok.py": "x = 1\n", bad_name: "owned = True\n"}))
    assert response.status_code == 400 and b"unsafe file path" in response.data
    assert not (tmp_path / "evil.py").exists()
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 0


def test_zip_symlinks_and_non_zip_files_are_rejected(app):
    client = app.test_client()
    sign_up(client)
    assert b"symbolic links" in upload_zip(client, zip_bytes({"a.py": "x = 1\n"}, symlink="link")).data
    assert b"Upload a ZIP file" in upload_zip(client, BytesIO(b"not a zip"), filename="notes.txt").data
    assert b"not a valid ZIP" in upload_zip(client, BytesIO(b"not a zip"), filename="broken.zip").data


def test_oversized_upload_shows_friendly_message(tmp_path):
    app = make_app(tmp_path, MAX_CONTENT_LENGTH=1024)
    client = app.test_client()
    sign_up(client)
    response = upload_zip(client, zip_bytes({"big.txt": "x" * 5000}))
    assert response.status_code == 302
    assert b"larger than the" in client.get(response.headers["Location"]).data


# ---------- Background analysis and progress ----------
def test_github_analysis_runs_and_redirects_through_progress(finished):
    client, analysis_id = finished
    status = client.get(f"/dashboard/{analysis_id}/status").get_json()
    assert status["status"] == "complete" and status["detail_url"].endswith(f"/dashboard/{analysis_id}")
    assert client.get(f"/dashboard/{analysis_id}/progress").status_code == 302  # finished -> results
    page = client.get(f"/dashboard/{analysis_id}").data
    assert b"billing" in page and b"commitActivityChart" in page


def test_analysis_runs_in_a_background_thread(tmp_path, fake_clone):
    app = make_app(tmp_path, ANALYSIS_INLINE=False)
    client = app.test_client()
    sign_up(client)
    analysis_id = int(analyze_github(client).headers["Location"].split("/")[-2])
    for _ in range(100):
        status = client.get(f"/dashboard/{analysis_id}/status").get_json()
        if status["status"] != "running":
            break
        time.sleep(0.05)
    assert status["status"] == "complete"


def test_failed_analysis_shows_safe_error(app, monkeypatch):
    def broken_clone(url):
        raise RuntimeError("secret internal path C:/Users/samue/instance")
    monkeypatch.setattr(analysis_jobs, "clone_public_repository", broken_clone)
    client = app.test_client()
    sign_up(client)
    analysis_id = int(analyze_github(client).headers["Location"].split("/")[-2])
    status = client.get(f"/dashboard/{analysis_id}/status").get_json()
    assert status["status"] == "failed" and status["error"] == analysis_jobs.UNEXPECTED_ERROR
    page = client.get(f"/dashboard/{analysis_id}/progress").data
    assert b"could not be completed" in page and b"secret internal path" not in page
    assert client.get(f"/dashboard/{analysis_id}").status_code == 302  # no results to show


def test_only_one_running_analysis_per_user(app):
    client = app.test_client()
    user_id = sign_up(client)
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO analyses (user_id, repository_name, source_type, status) VALUES (?, 'busy', 'github', 'running')", (user_id,))
        db.commit()
    response = analyze_github(client)
    assert "/progress" in response.headers["Location"]
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 1


def test_server_restart_marks_running_analyses_as_failed(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    user_id = sign_up(client)
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO analyses (user_id, repository_name, source_type, status) VALUES (?, 'x', 'github', 'running')", (user_id,))
        db.commit()
    restarted = make_app(tmp_path)
    with restarted.app_context():
        row = get_db().execute("SELECT status, error_message FROM analyses").fetchone()
    assert row["status"] == "failed" and "interrupted" in row["error_message"]


# ---------- Ownership checks ----------
def test_other_users_cannot_reach_any_analysis_route(app, finished):
    _, analysis_id = finished
    intruder = app.test_client()
    sign_up(intruder, "eve@example.com")
    for path in ("", "/investigate", "/timeline", "/report.pdf", "/progress", "/delete"):
        assert intruder.get(f"/dashboard/{analysis_id}{path}").status_code == 302, path
    assert intruder.get(f"/dashboard/{analysis_id}/status").status_code == 404
    data = {"csrf_token": token(intruder), "question": "Who worked on this?", "entity_id": "x"}
    intruder.post(f"/dashboard/{analysis_id}/ask-repository", data=data)
    intruder.post(f"/dashboard/{analysis_id}/delete", data={"csrf_token": token(intruder)})
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT COUNT(*) FROM analyses WHERE id = ?", (analysis_id,)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM investigation_notes").fetchone()[0] == 0


# ---------- Saved-analysis management ----------
def save_rows(app, user_id, rows):
    with app.app_context():
        db = get_db()
        for name, source, status in rows:
            db.execute("INSERT INTO analyses (user_id, repository_name, source_type, status) VALUES (?, ?, ?, ?)", (user_id, name, source, status))
        db.commit()


def test_dashboard_search_filter_and_sort(app):
    client = app.test_client()
    user_id = sign_up(client)
    save_rows(app, user_id, [("calculator", "github", "complete"), ("todo-app", "zip", "complete"),
                             ("calc_tools", "github", "failed"), ("100%_real", "zip", "complete")])
    page = client.get("/dashboard/?q=calc").data
    assert b"calculator" in page and b"calc_tools" in page and b"todo-app" not in page
    page = client.get("/dashboard/?source=zip").data
    assert b"todo-app" in page and b"calculator" not in page
    page = client.get("/dashboard/?status=failed").data
    assert b"calc_tools" in page and b"calculator" not in page
    assert b"100%_real" in client.get("/dashboard/?q=%25_").data and b"calculator" not in client.get("/dashboard/?q=%25_").data
    page = client.get("/dashboard/?sort=name").data.decode()
    assert page.index("100%_real") < page.index("calc_tools") < page.index("calculator") < page.index("todo-app")
    assert b"No analyses match" in client.get("/dashboard/?q=nothing-like-this").data
    assert client.get("/dashboard/?sort=DROP TABLE").status_code == 200  # unknown values fall back safely


def test_delete_requires_confirmation_page_and_removes_notes(app, finished):
    client, analysis_id = finished
    client.post(f"/dashboard/{analysis_id}/ask-repository", data={"csrf_token": token(client), "question": "Who worked on this?"})
    page = client.get(f"/dashboard/{analysis_id}/delete").data
    assert b"permanently removes" in page and b"1 saved investigation answer" in page
    response = client.post(f"/dashboard/{analysis_id}/delete", data={"csrf_token": token(client)})
    assert b"Deleted the analysis" in client.get(response.headers["Location"]).data
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM investigation_notes").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM analysis_results").fetchone()[0] == 0


def test_running_analysis_cannot_be_deleted(app):
    client = app.test_client()
    user_id = sign_up(client)
    save_rows(app, user_id, [("busy", "github", "running")])
    client.get("/dashboard/")
    client.post("/dashboard/1/delete", data={"csrf_token": token(client)})
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 1


# ---------- Repository questions and saved answers ----------
@pytest.mark.parametrize("question, expected", [
    ("Who worked on this project?", b"Ada: 2 commit(s)"),
    ("Which files are risky?", b"billing.py"),
    ("What libraries does it depend on?", b"express"),
    ("When was it most active?", b"busiest"),
    ("What are the core parts?", b"Parsed languages"),
])
def test_repository_questions_are_grounded(finished, question, expected):
    client, analysis_id = finished
    client.get(f"/dashboard/{analysis_id}/investigate")
    page = client.post(f"/dashboard/{analysis_id}/ask-repository", data={"csrf_token": token(client), "question": question}).data
    assert expected in page
    assert b"Verified facts" in page and b"Hypotheses" in page and b"Supporting evidence" in page


def test_entity_answers_include_related_commits(finished):
    client, analysis_id = finished
    client.get(f"/dashboard/{analysis_id}/investigate")
    page = client.post(f"/dashboard/{analysis_id}/ask", data={
        "csrf_token": token(client), "entity_id": "billing.py:1:total", "question": "Why did this change so often?"}).data
    assert b"Fix rounding bug" in page and b"/timeline?commit=" in page
    assert b"report" in client.post(f"/dashboard/{analysis_id}/ask", data={
        "csrf_token": token(client), "entity_id": "billing.py:1:total", "question": "What calls this?"}).data


def test_answers_are_saved_listed_and_removable(app, finished):
    client, analysis_id = finished
    client.get(f"/dashboard/{analysis_id}/investigate")
    client.post(f"/dashboard/{analysis_id}/ask-repository", data={"csrf_token": token(client), "question": "Where are the hotspots?"})
    page = client.get(f"/dashboard/{analysis_id}/investigate").data
    assert b"Investigation history" in page and b"Where are the hotspots?" in page
    with app.app_context():
        note_id = get_db().execute("SELECT id FROM investigation_notes").fetchone()[0]
    client.post(f"/dashboard/{analysis_id}/notes/{note_id}/delete", data={"csrf_token": token(client)})
    assert b"Where are the hotspots?" not in client.get(f"/dashboard/{analysis_id}/investigate").data


def test_ai_failure_falls_back_to_rule_based_answer(tmp_path, fake_clone, monkeypatch):
    app = make_app(tmp_path, OPENAI_API_KEY="sk-test-not-real")
    import openai

    class Broken:
        def __init__(self, **_kwargs):
            raise RuntimeError("network down")
    monkeypatch.setattr(openai, "OpenAI", Broken)
    client = app.test_client()
    sign_up(client)
    analysis_id = int(analyze_github(client).headers["Location"].split("/")[-2])
    client.get(f"/dashboard/{analysis_id}/investigate")
    page = client.post(f"/dashboard/{analysis_id}/ask-repository", data={"csrf_token": token(client), "question": "Who worked here?"}).data
    assert b"RULE-BASED, GROUNDED ANSWER" in page and b"sk-test-not-real" not in page


# ---------- Timeline and PDF ----------
def test_timeline_persists_commits_and_diffs(finished):
    client, analysis_id = finished
    page = client.get(f"/dashboard/{analysis_id}/timeline").data
    assert b"Fix rounding bug" in page
    with client.application.app_context():
        result = json.loads(get_db().execute("SELECT result_json FROM analysis_results").fetchone()[0])
    fix = next(item for item in result["timeline"] if item["message"] == "Fix rounding bug")
    assert any(item["path"] == "billing.py" for item in fix["files"]) and "round(sum(items), 2)" in fix["diff_excerpt"]
    assert b"round(sum(items), 2)" in client.get(f"/dashboard/{analysis_id}/timeline?commit={fix['hash']}").data


def test_pdf_report_includes_charts_and_saved_answers(finished):
    client, analysis_id = finished
    client.get(f"/dashboard/{analysis_id}/investigate")
    client.post(f"/dashboard/{analysis_id}/ask-repository", data={"csrf_token": token(client), "question": "Which files are risky?"})
    response = client.get(f"/dashboard/{analysis_id}/report.pdf")
    assert response.status_code == 200 and response.mimetype == "application/pdf" and response.data.startswith(b"%PDF")
    assert "attachment" in response.headers["Content-Disposition"]
    pypdf = pytest.importorskip("pypdf")
    text = "".join(page.extract_text() for page in pypdf.PdfReader(BytesIO(response.data)).pages)
    for expected in ("Commit activity", "Commits per contributor", "Investigation answers", "Which files are risky?", "Most-connected code"):
        assert expected in text, expected

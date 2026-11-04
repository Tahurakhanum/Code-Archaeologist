from pathlib import Path
from io import BytesIO
import zipfile
import pytest
from code_archaeologist import create_app

@pytest.fixture()
def app(tmp_path):
    return create_app({"TESTING": True, "SECRET_KEY": "test-key", "DATABASE": str(Path(tmp_path) / "test.sqlite3"), "REPOSITORY_STORAGE": str(Path(tmp_path) / "repositories"), "ANALYSIS_INLINE": True, "OPENAI_API_KEY": ""})

@pytest.fixture()
def client(app):
    return app.test_client()

def csrf(client):
    with client.session_transaction() as session:
        return session["csrf_token"]

def test_landing_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Unearth the story" in response.data

def test_signup_and_protected_dashboard(client):
    client.get("/auth/signup")
    response = client.post("/auth/signup", data={"csrf_token": csrf(client), "name": "Ada", "email": "ada@example.com", "password": "safe-password"})
    assert response.status_code == 302
    assert b"Welcome back, Ada" in client.get("/dashboard/").data

def test_dashboard_requires_login(client):
    assert client.get("/dashboard/").status_code == 302

def test_zip_analysis_is_saved_without_executing_source(client):
    client.get("/auth/signup")
    client.post("/auth/signup", data={"csrf_token": csrf(client), "name": "Ada", "email": "ada@example.com", "password": "safe-password"})
    client.get("/dashboard/new")
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("sample/main.py", "print('this must never run')\n")
        zip_file.writestr("sample/README.md", "Example")
    archive.seek(0)
    response = client.post("/dashboard/new", data={"csrf_token": csrf(client), "source_type": "zip", "archive": (archive, "sample.zip")}, content_type="multipart/form-data")
    assert response.status_code == 302
    detail = client.get(response.headers["Location"], follow_redirects=True)  # progress page -> results
    assert b"Total files" in detail.data
    assert b"this must never run" not in detail.data

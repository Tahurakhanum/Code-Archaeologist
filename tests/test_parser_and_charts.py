"""Tests for the upgraded code parser, relationships, activity charts, and investigation answers."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from git import Actor, Repo

from code_archaeologist import create_app
from code_archaeologist.database import get_db
from code_archaeologist.services.code_parser import extract_code_entities
from code_archaeologist.services.scanner import analyze_repository

TSX_SOURCE = '''import React, { useState } from "react";
import {
  Header,
} from "./layout";
const api = require("./api");

export const formatName = (user: User): string => user.first + " " + user.last;

const Greeting: React.FC<{ user: User }> = ({ user }) => (
  <p>Don't forget, {formatName(user)}!</p>
);

export default function App() {
  const handleClick = async (
    event: React.MouseEvent
  ) => {
    await saveCount(1);
  };
  return (
    <div onClick={handleClick}>
      <Greeting user={{ first: "a", last: "b" }} />
    </div>
  );
}

function saveCount(value: number) {
  // a brace in a comment {
  const message = `value is ${value} }`;
  return api.post("/count", { value, message });
}

export class CounterStore extends React.Component {
  increment(by: number): void {
    saveCount(by);
  }
  reset = () => {
    this.total = 0;
  };
}
export { saveCount as persist };
'''


def by_name(entities):
    return {entity["display_name"]: entity for entity in entities}


@pytest.fixture()
def parsed(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.tsx").write_text(TSX_SOURCE, encoding="utf-8")
    (tmp_path / "node_modules" / "lib").mkdir(parents=True)
    (tmp_path / "node_modules" / "lib" / "index.js").write_text("export function shouldBeSkipped() {}\n")
    (tmp_path / "service.py").write_text(
        "import os\nfrom .db import connect\n\nclass Service:\n    def save(self, item):\n        return helper(item)\n\n"
        "def helper(item):\n    return item\n", encoding="utf-8")
    return extract_code_entities(tmp_path)


def test_parser_detects_jsx_components_arrow_functions_and_methods(parsed):
    entities = by_name(parsed[0])
    assert entities["formatName"]["kind"] == "function"          # concise arrow function
    assert entities["Greeting"]["kind"] == "component"           # typed arrow returning JSX
    assert entities["App"]["kind"] == "component"                # function returning JSX
    assert entities["handleClick"]["kind"] == "function"         # multi-line arrow parameters
    assert entities["CounterStore"]["kind"] == "component"       # React class component
    assert entities["CounterStore.increment"]["kind"] == "method"
    assert entities["CounterStore.reset"]["kind"] == "method"    # arrow class field
    assert entities["Service.save"]["kind"] == "method"          # Python method via AST


def test_parser_finds_real_end_lines(parsed):
    entities = by_name(parsed[0])
    assert (entities["formatName"]["start_line"], entities["formatName"]["end_line"]) == (7, 7)
    # Braces in the TypeScript type, JSX text apostrophes, comments, and template strings are ignored.
    assert (entities["Greeting"]["start_line"], entities["Greeting"]["end_line"]) == (9, 11)
    assert (entities["saveCount"]["start_line"], entities["saveCount"]["end_line"]) == (26, 30)


def test_parser_links_calls_and_jsx_usage(parsed):
    entities = by_name(parsed[0])
    assert "formatName" in [link["name"] for link in entities["Greeting"]["calls"]]
    assert "Greeting" in [link["name"] for link in entities["App"]["calls"]]          # <Greeting /> usage
    callers = [link["name"] for link in entities["saveCount"]["called_by"]]
    assert "handleClick" in callers and "CounterStore.increment" in callers
    assert "Service.save" in [link["name"] for link in entities["helper"]["called_by"]]


def test_parser_records_imports_exports_and_skips_node_modules(parsed):
    files = {item["path"]: item for item in parsed[1]}
    assert "node_modules/lib/index.js" not in files
    tsx = files["src/App.tsx"]
    assert tsx["imports"] == ["react", "./layout", "./api"]
    assert {"formatName", "App (default)", "CounterStore", "persist"} <= set(tsx["exports"])
    assert files["service.py"]["imports"] == ["os", ".db"]


def make_repository(root: Path) -> None:
    repository = Repo.init(root)
    start = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    plan = [("Ada", 0), ("Ada", 0), ("Grace", 2), ("Ada", 5), ("Linus", 5)]
    for number, (author, day) in enumerate(plan):
        (root / "app.py").write_text(f"def step():\n    return {number}\n")
        repository.index.add(["app.py"])
        when = f"{int((start + timedelta(days=day)).timestamp())} +0000"  # raw Git date format
        repository.index.commit(f"Commit {number}", author=Actor(author, f"{author}@example.com"),
                                committer=Actor(author, f"{author}@example.com"), author_date=when, commit_date=when)


def test_activity_over_time_is_bucketed_with_gaps(tmp_path):
    make_repository(tmp_path)
    result = analyze_repository(tmp_path, True)
    activity = result["commit_activity"]
    assert activity["granularity"] == "day"
    assert len(activity["labels"]) == 6                      # 1 Oct to 6 Oct, including empty days
    assert activity["counts"] == [2, 0, 1, 0, 0, 2]
    series = {item["name"]: item["counts"] for item in result["contributor_activity"]["series"]}
    assert series["Ada"] == [2, 0, 0, 0, 0, 1]
    assert result["total_contributors"] == 3


# ---------- Web pages ----------
@pytest.fixture()
def app(tmp_path):
    return create_app({"TESTING": True, "SECRET_KEY": "test-key", "DATABASE": str(tmp_path / "test.sqlite3"),
                       "REPOSITORY_STORAGE": str(tmp_path / "repositories"), "OPENAI_API_KEY": "", "ANALYSIS_INLINE": True})


def sign_up(client, email):
    client.get("/auth/signup")
    with client.session_transaction() as session:
        token = session["csrf_token"]
    client.post("/auth/signup", data={"csrf_token": token, "name": "Ada", "email": email, "password": "safe-password"})
    with client.session_transaction() as session:
        return session["user_id"]


def save_analysis(app, user_id, result):
    with app.app_context():
        db = get_db()
        cursor = db.execute("INSERT INTO analyses (user_id, repository_name, source_type, source_url, status, summary) "
                            "VALUES (?, 'demo', 'github', NULL, 'complete', 'demo')", (user_id,))
        db.execute("INSERT INTO analysis_results (analysis_id, result_json, git_available) VALUES (?, ?, 1)",
                   (cursor.lastrowid, json.dumps(result)))
        db.commit()
        return cursor.lastrowid


@pytest.fixture()
def saved(app, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    make_repository(repo_root)
    (repo_root / "App.tsx").write_text(TSX_SOURCE, encoding="utf-8")
    client = app.test_client()
    user_id = sign_up(client, "ada@example.com")
    return client, save_analysis(app, user_id, analyze_repository(repo_root, True))


def test_detail_page_includes_all_charts(saved):
    client, analysis_id = saved
    page = client.get(f"/dashboard/{analysis_id}").data
    for chart_id in (b"commitActivityChart", b"contributorChart", b"contributorActivityChart", b"fileFrequencyChart"):
        assert chart_id in page
    assert b'id="chart-data"' in page and b"charts.js" in page


def test_old_analysis_without_activity_data_still_renders(app):
    client = app.test_client()
    user_id = sign_up(client, "old@example.com")
    old_result = {"total_files": 1, "source_files": 1, "file_types": [[".py", 1]], "total_commits": 3,
                  "contributors": [{"name": "Ada", "commits": 3}], "recent_commits": [], "frequently_modified_files": [],
                  "history_note": "old", "entities": [], "risks": []}
    page = client.get(f"/dashboard/{save_analysis(app, user_id, old_result)}").data
    assert b"Run a new analysis" in page


def test_investigate_page_shows_relationships(saved):
    client, analysis_id = saved
    page = client.get(f"/dashboard/{analysis_id}/investigate?entity=App.tsx:26:saveCount").data
    assert b"RELATIONSHIPS" in page and b"handleClick" in page and b"./layout" in page


def test_break_question_uses_callers(saved):
    client, analysis_id = saved
    client.get(f"/dashboard/{analysis_id}/investigate")
    with client.session_transaction() as session:
        token = session["csrf_token"]
    page = client.post(f"/dashboard/{analysis_id}/ask", data={
        "csrf_token": token, "entity_id": "App.tsx:26:saveCount", "question": "What could break if it changes?"}).data
    assert b"referenced by" in page


def test_users_cannot_open_each_others_analyses(app, saved):
    _, analysis_id = saved
    intruder = app.test_client()
    sign_up(intruder, "eve@example.com")
    response = intruder.get(f"/dashboard/{analysis_id}")
    assert response.status_code == 302
    assert intruder.get(f"/dashboard/{analysis_id}/investigate").status_code == 302

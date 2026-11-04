"""Grounded answers to investigation questions, with optional backend-only AI.

Every answer has the same shape so templates and the PDF can show it consistently:
    {"mode": "fallback" | "ai", "facts": [...], "hypotheses": [...], "text": "...",
     "evidence": [{"kind", "label", "detail", "ref"}], "limitation": "..."}

The evidence list is always built by this module from saved analysis data, even in
AI mode, so supporting commits and files never depend on what the model says.
The API key is read from the server config and is never sent to the browser.
"""
from collections import Counter

from flask import current_app

from .explanations import explain_entity, file_info_for, is_exported, link_names

MAX_QUESTION_LENGTH = 800
AI_INSTRUCTIONS = (
    "You explain a software repository using ONLY the evidence supplied. Answer in two short sections titled "
    "'Verified facts:' and 'Hypotheses:'. Verified facts must be directly supported by the evidence; cite commit "
    "hashes, file paths, and dates where possible. Put any interpretation under Hypotheses. Never present ownership, "
    "effort, expertise, or a bug as a fact. If the evidence cannot answer the question, say so."
)

# Question keywords, checked in order. More specific topics come first.
ENTITY_TOPICS = [
    ("contributors", ("who", "developer", "contributor", "author", "worked")),
    ("relationships", ("call", "uses", "used by", "depend", "import", "relationship", "related", "connect")),
    ("risk", ("risk", "break", "impact", "safe to", "affect")),
    ("history", ("frequent", "change", "changed", "history", "why", "when", "commit")),
    ("purpose", ("what", "does", "purpose", "explain", "how")),
]
REPOSITORY_TOPICS = [
    ("contributors", ("who", "developer", "contributor", "author", "team", "worked", "people")),
    ("risk", ("risk", "hotspot", "problem", "bug", "fragile", "maintenance", "concern", "worry", "unstable")),
    ("dependencies", ("depend", "import", "librar", "package", "framework", "third-party", "third party")),
    ("activity", ("when", "active", "activity", "timeline", "history", "recent", "time", "date", "evolve")),
    ("structure", ("structure", "language", "file", "architecture", "component", "main", "important", "core",
                   "organi", "layout", "folder", "entry")),
]


def answer_question(entity: dict, result: dict, question: str) -> dict:
    """Answer a question about one function, component, method, or class."""
    question = question.strip()[:MAX_QUESTION_LENGTH]
    if not question:
        return _empty_answer("Ask a question about the selected function or class.")
    answer = _entity_rule_based(entity, result, question)
    evidence_for_ai = {
        "entity": {key: entity.get(key) for key in ("path", "kind", "display_name", "start_line", "end_line", "excerpt")},
        "calls": entity.get("calls", []), "called_by": entity.get("called_by", []),
        "file_imports_exports": file_info_for(entity, result),
        "file_activity": _file_activity(entity["path"], result),
        "related_commits": related_commits(entity["path"], result),
        "history_note": result.get("history_note"),
    }
    return _maybe_ai(answer, question, evidence_for_ai)


def answer_repository_question(result: dict, question: str) -> dict:
    """Answer a question about the whole repository."""
    question = question.strip()[:MAX_QUESTION_LENGTH]
    if not question:
        return _empty_answer("Ask a question about the repository.")
    answer = _repository_rule_based(result, question)
    evidence_for_ai = {"summary": repository_summary(result), "rule_based_findings": answer["facts"]}
    return _maybe_ai(answer, question, evidence_for_ai)


# --- AI (optional) -----------------------------------------------------------------------
def _maybe_ai(answer: dict, question: str, evidence: dict) -> dict:
    api_key = current_app.config.get("OPENAI_API_KEY")
    if not api_key:
        return answer
    try:
        from openai import OpenAI
        response = OpenAI(api_key=api_key).responses.create(
            model=current_app.config["OPENAI_MODEL"], instructions=AI_INSTRUCTIONS,
            input=f"Question: {question}\n\nEvidence (JSON): {evidence}",
        )
        text = (response.output_text or "").strip()
    except Exception:
        current_app.logger.warning("AI answer failed; using the rule-based answer instead.")
        return answer  # an unavailable AI service must never block an investigation
    if not text:
        return answer
    return {**answer, "mode": "ai", "text": text,
            "limitation": "AI-generated from the saved evidence listed below. Check important claims against the commits and files."}


# --- Rule-based answers about one entity -------------------------------------------------
def _entity_rule_based(entity: dict, result: dict, question: str) -> dict:
    topic = _topic(question, ENTITY_TOPICS)
    label = entity.get("display_name", entity["name"])
    activity = _file_activity(entity["path"], result)
    commits = related_commits(entity["path"], result)
    callers, calls = entity.get("called_by", []), entity.get("calls", [])
    facts, hypotheses = [], []

    if topic == "contributors":
        if activity and activity["contributors"]:
            facts.append(f"Commits touching {entity['path']} name these author(s): {', '.join(activity['contributors'])}.")
            authors = Counter(commit["author"] for commit in commits)
            if authors:
                facts.append("In the recent saved timeline: " + ", ".join(f"{name} ({count} commit(s))" for name, count in authors.most_common(5)) + ".")
        else:
            facts.append("No contributor evidence is available for this file in the saved analysis.")
        hypotheses.append("Commit authorship shows who changed the file, not who owns the code or how much effort they spent.")
    elif topic == "relationships":
        imports = file_info_for(entity, result).get("imports", [])
        facts.append(f"{label} is referenced by {link_names(callers) if callers else 'no detected code'}.")
        facts.append(f"It references {link_names(calls) if calls else 'no other detected code'}.")
        facts.append(f"Its file imports: {', '.join(imports[:10]) if imports else 'nothing detected'}.")
        hypotheses.append("Dynamic calls, callbacks, or files that were not parsed may add relationships not shown here.")
    elif topic == "risk":
        facts.append(f"{label} is a {entity['kind']} in {entity['path']}.")
        facts.append(f"Detected callers: {link_names(callers)}." if callers else "No callers were detected by name.")
        if is_exported(entity, file_info_for(entity, result)):
            facts.append("It is exported, so modules outside this file may depend on it.")
        risks = [risk for risk in result.get("risks", []) if risk["file"] == entity["path"]]
        facts += [f"Maintenance signal on its file: {risk['reason']} ({risk['evidence']})" for risk in risks]
        hypotheses.append("Those callers, their tests, and modules importing this file could be affected by a change. "
                          "Name-based matching is not a complete call graph, so confirm before editing.")
    elif topic == "history":
        if activity:
            facts.append(f"{entity['path']} appears in {activity['changes']} analyzed commit(s), "
                         f"{activity['bug_fixes']} of them with fix-related messages.")
        else:
            facts.append("No Git change history is available for this file.")
        if commits:
            facts.append(f"{len(commits)} of the saved recent commits changed this file (listed as evidence below).")
        hypotheses.append("Frequent changes can reflect active development, refactoring, or a maintenance hotspot; "
                          "read the listed commit messages and diffs before deciding why.")
    else:  # purpose, or a general question
        base = explain_entity(entity, result)
        facts += base["facts"]
        doc = leading_comment(entity.get("excerpt", ""))
        if doc:
            facts.insert(1, f"Its own comment/docstring says: “{doc}”")
        hypotheses.append(f"The name “{entity['name']}”, its comments, callers, and tests are the best clues to its exact purpose.")
        hypotheses += base["hypotheses"][:1]

    evidence = [{"kind": "code", "label": label, "detail": f"{entity['path']}, lines {entity['start_line']}–{entity['end_line']}", "ref": entity["id"]}]
    evidence += [{"kind": "code", "label": link["name"], "detail": f"{'caller' if link in callers else 'called'} · {link['path']}:{link['line']}", "ref": link["id"]}
                 for link in (callers + calls)[:6]]
    evidence += [_commit_evidence(commit) for commit in commits[:5]]
    return _answer(facts, hypotheses, evidence)


# --- Rule-based answers about the whole repository ---------------------------------------
def _repository_rule_based(result: dict, question: str) -> dict:
    topic = _topic(question, REPOSITORY_TOPICS)
    facts, hypotheses, evidence = [], [], []
    has_history = bool(result.get("total_commits"))

    if topic == "contributors":
        contributors, total = result.get("contributors", []), max(result.get("total_commits", 0), 1)
        if contributors:
            facts.append(f"{result.get('total_contributors', len(contributors))} contributor(s) authored the {result.get('total_commits', 0)} analyzed commits.")
            facts += [f"{item['name']}: {item['commits']} commit(s) ({round(item['commits'] * 100 / total)}% of analyzed commits)." for item in contributors[:5]]
            for developer in result.get("developer_areas", [])[:5]:
                folders = Counter(path.split("/")[0] if "/" in path else "(root)" for path in developer["files"])
                evidence.append({"kind": "contributor", "label": developer["name"],
                                 "detail": f"{developer['file_count']} file(s) changed, mostly in {', '.join(name for name, _ in folders.most_common(3))}", "ref": None})
        else:
            facts.append("No contributor data is available because this analysis has no Git history.")
        hypotheses.append("Commit counts do not measure effort, expertise, or ownership; one large commit can outweigh many small ones.")
    elif topic == "risk":
        risks = result.get("risks", [])
        facts += [f"{risk['file']}: {risk['reason']} — {risk['evidence']}" for risk in risks[:6]] or ["No maintenance signals were recorded."]
        evidence += [{"kind": "file", "label": item["path"], "detail": f"changed in {item['changes']} commit(s), {item.get('bug_fixes', 0)} fix-related", "ref": None}
                     for item in result.get("file_activity", [])[:5]]
        hypotheses.append("Files that change often, attract fix commits, or depend on one person are good places to add tests and reviews. "
                          "These are signals to investigate, not confirmed bugs.")
    elif topic == "dependencies":
        external, internal = _dependency_counts(result)
        if external:
            facts.append("Most-used external packages/modules: " + ", ".join(f"{name} ({count} file(s))" for name, count in external.most_common(10)) + ".")
        else:
            facts.append("No external imports were detected in the parsed files.")
        facts.append(f"{internal} import(s) point to other files inside the repository.")
        evidence += [{"kind": "file", "label": item["path"], "detail": "imports: " + ", ".join(item["imports"][:6]), "ref": None}
                     for item in sorted(result.get("code_files", []), key=lambda f: len(f.get("imports", [])), reverse=True)[:4] if item.get("imports")]
        hypotheses.append("Widely imported packages are the frameworks the project relies on; upgrading them could affect many files.")
    elif topic == "activity":
        activity = result.get("commit_activity")
        if activity:
            active = [(label, count) for label, count in zip(activity["labels"], activity["counts"]) if count]
            busiest = max(active, key=lambda item: item[1])
            facts.append(f"Analyzed commits run from {active[0][0]} to {active[-1][0]} ({len(active)} active {activity['granularity']}(s)).")
            facts.append(f"The busiest {activity['granularity']} was {busiest[0]} with {busiest[1]} commit(s).")
        elif has_history:
            facts.append(f"{result.get('total_commits')} commits were analyzed. Re-run the analysis to see activity by period.")
        else:
            facts.append(result.get("history_note", "No Git history is available."))
        evidence += [_commit_evidence(commit) for commit in result.get("recent_commits", [])[:5]]
        hypotheses.append("Quiet periods can mean a stable project, work happening in another branch, or history that was not cloned.")
    elif topic == "structure":
        facts += _structure_facts(result)
        evidence += [{"kind": "code", "label": item["display_name"], "detail": f"used by {len(item['called_by'])} · {item['path']}:{item['start_line']}", "ref": item["id"]}
                     for item in most_referenced(result)]
        hypotheses.append("The most-referenced functions and components are likely core building blocks; start reading there.")
    else:
        facts.append(f"The repository has {result.get('total_files', 0)} files ({result.get('source_files', 0)} source files) "
                     f"and {result.get('total_commits', 0)} analyzed commit(s) by {result.get('total_contributors', len(result.get('contributors', [])))} contributor(s).")
        facts += _structure_facts(result)[:2]
        if result.get("frequently_modified_files"):
            top = result["frequently_modified_files"][0]
            facts.append(f"The most frequently modified file is {top['path']} ({top['changes']} commits).")
        evidence += [_commit_evidence(commit) for commit in result.get("recent_commits", [])[:3]]
        hypotheses.append("Ask about contributors, risks, dependencies, activity, or structure for a more specific answer.")
    return _answer(facts, hypotheses, evidence, scope="repository")


# --- Helpers shared with templates, tests, and the PDF report ----------------------------
def related_commits(path: str, result: dict) -> list[dict]:
    """Saved timeline commits (the most recent 40) that changed ``path``."""
    return [commit for commit in result.get("timeline", []) if any(item["path"] == path for item in commit.get("files", []))]


def most_referenced(result: dict, limit: int = 5) -> list[dict]:
    entities = [item for item in result.get("entities", []) if item.get("called_by")]
    return sorted(entities, key=lambda item: len(item["called_by"]), reverse=True)[:limit]


def repository_summary(result: dict) -> dict:
    """A compact version of the analysis to send to the AI model."""
    return {
        "totals": {key: result.get(key) for key in ("total_files", "source_files", "total_commits", "total_contributors")},
        "file_types": result.get("file_types", []), "contributors": result.get("contributors", [])[:8],
        "frequently_modified_files": result.get("frequently_modified_files", [])[:8], "risks": result.get("risks", [])[:8],
        "recent_commits": result.get("recent_commits", [])[:8],
        "most_referenced_code": [{"name": item["display_name"], "path": item["path"], "callers": len(item["called_by"])} for item in most_referenced(result, 8)],
        "history_note": result.get("history_note"),
    }


def leading_comment(excerpt: str) -> str:
    """Return the first comment or docstring line inside an excerpt, if there is one."""
    for line in excerpt.splitlines()[1:8]:
        text = line.strip().strip('"\'').lstrip("/*#").strip()
        if line.strip().startswith(('"""', "'''", "//", "/*", "*", "#")) and len(text) > 3:
            return text[:200]
    return ""


def _structure_facts(result: dict) -> list[str]:
    facts = []
    if result.get("file_types"):
        facts.append("Most common file types: " + ", ".join(f"{ext} ({count})" for ext, count in result["file_types"][:5]) + ".")
    languages = Counter(item["language"] for item in result.get("code_files", []))
    if languages:
        facts.append("Parsed languages: " + ", ".join(f"{name} ({count} file(s))" for name, count in languages.most_common()) + ".")
    kinds = Counter(item["kind"] for item in result.get("entities", []))
    if kinds:
        facts.append("Detected code: " + ", ".join(f"{count} {kind}(s)" for kind, count in kinds.most_common()) + ".")
    folders = Counter(item["path"].split("/")[0] for item in result.get("code_files", []) if "/" in item["path"])
    if folders:
        facts.append("Top-level source folders: " + ", ".join(f"{name}/ ({count} file(s))" for name, count in folders.most_common(5)) + ".")
    return facts or ["No parsed source structure is available for this analysis."]


def _dependency_counts(result: dict) -> tuple[Counter, int]:
    external, internal = Counter(), 0
    for item in result.get("code_files", []):
        packages = set()
        for name in item.get("imports", []):
            if name.startswith((".", "/")):
                internal += 1
            else:  # "@scope/pkg/x" -> "@scope/pkg", "react-dom/client" -> "react-dom", "os.path" -> "os"
                parts = name.split("/")
                root = "/".join(parts[:2]) if name.startswith("@") else parts[0]
                packages.add(root.split(".")[0] if item["language"] == "Python" else root)
        external.update(packages)
    return external, internal


def _file_activity(path: str, result: dict):
    return next((item for item in result.get("file_activity", []) if item["path"] == path), None)


def _commit_evidence(commit: dict) -> dict:
    return {"kind": "commit", "label": commit["hash"], "detail": f"{commit['message']} — {commit['author']}, {commit['timestamp']}", "ref": commit["hash"]}


def _topic(question: str, topics: list) -> str:
    lower = question.lower()
    return next((name for name, words in topics if any(word in lower for word in words)), "general")


def _answer(facts: list, hypotheses: list, evidence: list, scope: str = "code") -> dict:
    return {"mode": "fallback", "facts": facts, "hypotheses": hypotheses, "evidence": evidence, "text": "",
            "limitation": f"Rule-based answer built only from the saved analysis ({scope} evidence below). "
                          "Configure OPENAI_API_KEY on the server for optional AI-written answers."}


def _empty_answer(message: str) -> dict:
    return {"mode": "fallback", "facts": [], "hypotheses": [], "evidence": [], "text": message, "limitation": "No question was provided."}

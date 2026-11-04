"""Evidence-based maintenance signals. These are prompts to investigate, never bug claims."""


def detect_risks(result: dict) -> list[dict]:
    risks = []
    total_commits = max(result.get("total_commits", 0), 1)
    for item in result.get("file_activity", [])[:10]:
        path, changes, authors, bug_fixes = item["path"], item["changes"], item["contributors"], item["bug_fixes"]
        if changes >= max(3, total_commits * 0.20):
            risks.append({"level": "attention", "file": path, "reason": "Frequently modified", "evidence": f"Changed in {changes} of {total_commits} analyzed commits."})
        if len(authors) >= 4:
            risks.append({"level": "attention", "file": path, "reason": "Many contributors", "evidence": f"Touched by {len(authors)} contributors: {', '.join(authors[:4])}."})
        if changes >= 3 and len(authors) == 1:
            risks.append({"level": "watch", "file": path, "reason": "Knowledge concentration", "evidence": f"All {changes} observed changes were by {authors[0]}."})
        if bug_fixes >= 2:
            risks.append({"level": "watch", "file": path, "reason": "Repeated bug-fix association", "evidence": f"Touched by {bug_fixes} commits whose messages suggest a fix."})
    return risks[:12]

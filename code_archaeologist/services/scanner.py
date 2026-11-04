"""Read-only repository inspection; this module never imports or runs project files."""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from git import InvalidGitRepositoryError, Repo
from git.diff import NULL_TREE
from .risk_detection import detect_risks
from .code_parser import extract_code_entities

SOURCE_EXTENSIONS = {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rb", ".php", ".html", ".css", ".sql", ".rs"}


def analyze_repository(root: Path, git_available: bool, progress=None) -> dict:
    """Build the saved analysis result. ``progress`` (optional) receives short status messages."""
    report = progress or (lambda message: None)
    report("Scanning files and file types…")
    files = [path for path in root.rglob("*") if path.is_file() and ".git" not in path.parts]
    extension_counts = Counter((path.suffix.lower() or "[no extension]") for path in files)
    result = {
        "total_files": len(files),
        "source_files": sum(path.suffix.lower() in SOURCE_EXTENSIONS for path in files),
        "file_types": extension_counts.most_common(8),
        "total_commits": 0,
        "contributors": [],
        "recent_commits": [],
        "frequently_modified_files": [],
        "history_note": "No Git history is available for this source archive.",
    }
    report("Parsing functions, classes, and components…")
    entities, code_files = extract_code_entities(root)
    result["entities"] = entities
    result["code_files"] = code_files
    if git_available:
        report("Reading Git history, contributors, and diffs…")
        result.update(_read_git_history(root))
    report("Detecting maintenance signals…")
    result["risks"] = detect_risks(result)
    return result


def _read_git_history(root: Path) -> dict:
    try:
        repository = Repo(root, search_parent_directories=False)
        commits = list(repository.iter_commits(max_count=500))
    except (InvalidGitRepositoryError, ValueError):
        return {"history_note": "Git metadata was present but its history could not be read."}
    authors, touched = Counter(), Counter()
    file_authors, file_bug_fixes, contributor_files = defaultdict(set), Counter(), defaultdict(set)
    recent, timeline, commit_events = [], [], []
    for commit in commits:
        name = commit.author.name or "Unknown contributor"
        authors[name] += 1
        commit_events.append((datetime.fromtimestamp(commit.committed_date, timezone.utc), name))
        try:
            changed_files = commit.stats.files.keys()
            touched.update(changed_files)
            is_fix = any(word in (commit.summary or "").lower() for word in ("fix", "bug", "patch", "repair"))
            for path in changed_files:
                file_authors[path].add(name)
                contributor_files[name].add(path)
                if is_fix:
                    file_bug_fixes[path] += 1
        except Exception:
            pass
        if len(recent) < 10:
            recent.append({
                "hash": commit.hexsha[:8], "message": commit.summary or "(no message)", "author": name,
                "timestamp": datetime.fromtimestamp(commit.committed_date, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            })
        if len(timeline) < 40:
            timeline.append(_timeline_entry(commit))
    top_authors = [name for name, _ in authors.most_common(5)]
    return {
        **_activity_over_time(commit_events, top_authors),
        "total_commits": len(commits),
        "total_contributors": len(authors),
        "contributors": [{"name": name, "commits": count} for name, count in authors.most_common(10)],
        "frequently_modified_files": [{"path": path, "changes": count} for path, count in touched.most_common(10)],
        "file_activity": [{"path": path, "changes": count, "contributors": sorted(file_authors[path]), "bug_fixes": file_bug_fixes[path]} for path, count in touched.most_common(25)],
        "developer_areas": [{"name": name, "files": sorted(files)[:12], "file_count": len(files)} for name, files in sorted(contributor_files.items(), key=lambda item: len(item[1]), reverse=True)[:10]],
        "recent_commits": recent,
        "timeline": timeline,
        "history_note": "Git history analyzed from up to 500 most recent commits.",
    }


def _activity_over_time(events: list[tuple[datetime, str]], top_authors: list[str]) -> dict:
    """Count commits per day, week, or month for the activity charts.

    The bucket size is picked from how long the history is, and empty periods are
    filled with 0 so the charts show real gaps in activity.
    """
    if not events:
        return {}
    first, last = min(when for when, _ in events), max(when for when, _ in events)
    span_days = (last - first).days
    granularity = "day" if span_days <= 45 else "week" if span_days <= 370 else "month"

    def bucket(when: datetime) -> date:
        if granularity == "day":
            return when.date()
        if granularity == "week":
            return when.date() - timedelta(days=when.weekday())  # Monday of that week
        return date(when.year, when.month, 1)

    def next_bucket(current: date) -> date:
        if granularity == "day":
            return current + timedelta(days=1)
        if granularity == "week":
            return current + timedelta(days=7)
        return date(current.year + current.month // 12, current.month % 12 + 1, 1)

    buckets, current = [], bucket(first)
    while current <= bucket(last):
        buckets.append(current)
        current = next_bucket(current)
    position = {value: index for index, value in enumerate(buckets)}
    totals = [0] * len(buckets)
    per_author = {name: [0] * len(buckets) for name in top_authors}
    others = [0] * len(buckets)
    for when, name in events:
        index = position[bucket(when)]
        totals[index] += 1
        (per_author[name] if name in per_author else others)[index] += 1
    label_format = "%b %Y" if granularity == "month" else "%d %b %Y"
    labels = [value.strftime(label_format) for value in buckets]
    series = [{"name": name, "counts": counts} for name, counts in per_author.items()]
    if any(others):
        series.append({"name": "Other contributors", "counts": others})
    return {
        "commit_activity": {"granularity": granularity, "labels": labels, "counts": totals},
        "contributor_activity": {"granularity": granularity, "labels": labels, "series": series},
    }


def _timeline_entry(commit) -> dict:
    """Return a bounded, text-only commit record suitable for SQLite storage."""
    try:
        stats = commit.stats.files
        files = [{
            "path": path,
            "insertions": values.get("insertions", 0),
            "deletions": values.get("deletions", 0),
            "lines": values.get("lines", 0),
        } for path, values in list(stats.items())[:30]]
    except Exception:
        files = []
    try:
        # For normal commits compare parent -> commit, so + and - reflect the
        # selected commit's actual additions and deletions.
        patches = (commit.parents[0].diff(commit, create_patch=True)
                   if commit.parents else commit.diff(NULL_TREE, create_patch=True))
        pieces = []
        for patch in list(patches)[:8]:
            content = patch.diff.decode("utf-8", errors="replace")
            pieces.append(content[:1800])
        diff_excerpt = "\n".join(pieces)[:7000]
    except Exception:
        diff_excerpt = "Diff excerpt was unavailable for this commit."
    return {
        "hash": commit.hexsha[:8],
        "message": commit.summary or "(no message)",
        "author": commit.author.name or "Unknown contributor",
        "timestamp": datetime.fromtimestamp(commit.committed_date, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "files": files,
        "diff_excerpt": diff_excerpt or "No textual diff is available (the change may be binary or empty).",
    }

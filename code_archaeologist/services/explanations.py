"""Grounded fallback explanations when no LLM key is configured."""


def file_info_for(entity: dict, result: dict) -> dict:
    """Return the saved imports/exports record for the entity's file (empty for old analyses)."""
    return next((item for item in result.get("code_files", []) if item["path"] == entity["path"]), {})


def link_names(links: list[dict], limit: int = 6) -> str:
    names = [f"{link['name']} ({link['path']}:{link['line']})" for link in links[:limit]]
    extra = len(links) - limit
    return ", ".join(names) + (f" and {extra} more" if extra > 0 else "")


def is_exported(entity: dict, file_info: dict) -> bool:
    exported = {item.replace(" (default)", "") for item in file_info.get("exports", [])}
    return entity["name"] in exported


def explain_entity(entity: dict, result: dict) -> dict:
    activity = next((item for item in result.get("file_activity", []) if item["path"] == entity["path"]), None)
    file_info = file_info_for(entity, result)
    label = entity.get("display_name", entity["name"])
    calls, callers = entity.get("calls", []), entity.get("called_by", [])
    has_relationships = "calls" in entity  # analyses made before the parser upgrade do not have them

    facts = [
        f"{label} is a {entity['kind']} in {entity['path']} (lines {entity['start_line']}–{entity['end_line']}).",
        f"It spans {entity['end_line'] - entity['start_line'] + 1} line(s); the saved excerpt shows up to the first 40.",
    ]
    if calls:
        facts.append(f"Its body references {len(calls)} other detected function(s)/class(es): {link_names(calls)}.")
    if callers:
        facts.append(f"It is referenced by {len(callers)} detected function(s)/class(es): {link_names(callers)}.")
    if is_exported(entity, file_info):
        facts.append("It is exported from its file, so other modules can import it.")
    if file_info.get("imports"):
        facts.append(f"Its file imports: {', '.join(file_info['imports'][:8])}.")
    if activity:
        facts.append(f"Its file appears in {activity['changes']} analyzed commit(s) and was touched by {len(activity['contributors'])} contributor(s).")
    else:
        facts.append("No file-level Git activity was available for this entity.")

    hypotheses = []
    if callers:
        hypotheses.append(f"Changing {label} could affect {link_names(callers, 4)}; review those callers and their tests first.")
    elif has_relationships:
        hypotheses.append("No callers were found by name among detected code. It may be an entry point, called dynamically, "
                          "used from a file that was not parsed, or unused.")
    else:
        hypotheses.append("Review callers and tests before changing this code. Re-run the analysis to detect call relationships.")
    if entity["kind"] == "component":
        hypotheses.append("As a UI component, changes may affect every screen that renders it; check its props and parent components.")
    if activity and activity["changes"] >= 3:
        hypotheses.append("Frequent file changes may indicate active development, refactoring, or a maintenance hotspot; "
                          "commit messages and diffs should be reviewed before drawing conclusions.")
    return {"facts": facts, "hypotheses": hypotheses,
            "limitation": "Rule-based explanation grounded in the saved source, detected relationships, and Git metadata. "
                          "Relationships are name-based matches, not a complete call graph."}

"""Safe, read-only extraction of code entities from supported source files.

Nothing in this module imports or runs repository code:
- Python files are read with the standard-library ``ast`` parser.
- JavaScript, TypeScript, JSX, TSX, Java and C# use line-based regular
  expressions plus a small brace matcher that finds where a block ends.

Every entity also gets simple relationships ("calls" / "called_by"). These are
name-based matches, so they are investigation hints rather than a full call graph.
"""
import ast
import re
from pathlib import Path

MAX_SOURCE_BYTES = 256 * 1024
MAX_ENTITIES = 300
EXCERPT_LINES = 40
MAX_BLOCK_LINES = 400
MAX_LINKS = 15
MAX_IMPORTS = 30

LANGUAGES = {
    ".py": "Python",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript (JSX)",
    ".ts": "TypeScript", ".tsx": "TypeScript (TSX)",
    ".java": "Java", ".cs": "C#",
}
SUPPORTED_EXTENSIONS = set(LANGUAGES)
JS_FAMILY = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"}

# Generated or third-party folders add noise (and can be huge), so they are skipped.
SKIP_DIRECTORIES = {".git", "node_modules", "dist", "build", "out", ".next", "coverage",
                    "vendor", "venv", ".venv", "__pycache__", "bin", "obj"}

# Words that look like "name(" but are language keywords, not functions.
KEYWORDS = {"if", "for", "while", "switch", "catch", "function", "return", "else", "do", "try",
            "with", "new", "typeof", "await", "super", "import", "export", "using", "lock", "foreach"}
# Very common names that would create misleading call links.
LINK_STOPLIST = {"constructor", "__init__", "render", "toString", "get", "set", "main", "run"}

NAME = r"[A-Za-z_$][\w$]*"

# --- JavaScript / TypeScript / JSX / TSX -------------------------------------------------
JS_CLASS = re.compile(rf"^\s*(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+({NAME})")
JS_FUNCTION = re.compile(rf"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s*\*?\s*({NAME})\s*[<(]")
JS_VARIABLE = re.compile(rf"^\s*(?:export\s+)?(?:const|let|var)\s+({NAME})\s*(?::[^=]+)?=\s*(.*)$")
JS_METHOD = re.compile(
    rf"^\s+(?:(?:public|private|protected|static|readonly|override|abstract|async|get|set)\s+)*\*?\s*"
    rf"(#?{NAME})\s*(?:<[^>]*>)?\s*\([^)]*\)\s*(?::\s*[^{{;]+)?\s*\{{\s*$")
JS_CLASS_FIELD = re.compile(
    rf"^\s+(?:(?:public|private|protected|static|readonly|override)\s+)*(#?{NAME})\s*(?::[^=]+)?=\s*(.*)$")
# What comes after "=" when a variable holds a function: an arrow function, a
# function expression, or a React wrapper such as memo(...) / forwardRef(...).
ARROW_START = re.compile(
    rf"^(?:(?:React\.)?(?:memo|forwardRef|useCallback)\s*\(\s*)?(?:async\s+)?"
    rf"(?:function\b|(?:<[^>]*>\s*)?(?:\([^()]*(?:\([^()]*\)[^()]*)*\)|{NAME})\s*(?::\s*[^=;]+?)?\s*=>)",
    re.S)
JSX_RETURN = re.compile(r"(?:return|=>)\s*\(?\s*<[A-Za-z>]")
REACT_CLASS = re.compile(r"extends\s+(?:React\.)?(?:Component|PureComponent)\b")

JS_IMPORT = re.compile(r"""^\s*import\s+(?:type\s+)?(?:[\w*{}\s,$]+?\s+from\s+)?["']([^"']+)["']""", re.M)
JS_REQUIRE = re.compile(r"""\b(?:require|import)\(\s*["']([^"']+)["']\s*\)""")
JS_EXPORT_DECL = re.compile(
    rf"^\s*export\s+(default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:async\s+)?"
    rf"(?:function\s*\*?|class|const|let|var|interface|type|enum)\s+({NAME})", re.M)
JS_EXPORT_LIST = re.compile(r"^\s*export\s*\{([^}]*)\}", re.M)
JS_EXPORT_DEFAULT = re.compile(rf"^\s*export\s+default\s+({NAME})\s*;?\s*$", re.M)
CJS_EXPORT = re.compile(rf"^\s*(?:module\.exports\s*=\s*({NAME})|(?:module\.)?exports\.({NAME})\s*=)", re.M)

# --- Java / C# ---------------------------------------------------------------------------
JAVA_CLASS = re.compile(
    rf"^\s*(?:(?:public|private|protected|internal|static|abstract|final|sealed|partial)\s+)*"
    rf"(?:class|interface|enum|record|struct)\s+({NAME})")
JAVA_METHOD = re.compile(
    r"^\s*(?:(?:public|private|protected|internal|static|final|abstract|async|virtual|override|"
    r"synchronized|sealed|extern|new)\s+)+[\w<>\[\],.?\s]+?\s+([A-Za-z_]\w*)\s*\(")
JAVA_IMPORT = re.compile(r"^\s*(?:import|using)\s+(?:static\s+)?([\w.*]+)\s*;", re.M)
JAVA_EXPORT = re.compile(
    rf"^\s*public\s+(?:(?:static|abstract|final|sealed|partial)\s+)*(?:class|interface|enum|record|struct)\s+({NAME})",
    re.M)


def extract_code_entities(root: Path) -> tuple[list[dict], list[dict]]:
    """Return (entities, files) for every supported source file under ``root``."""
    entities, files, bodies = [], [], {}
    for path in sorted(root.rglob("*")):
        if not _is_candidate(path, root):
            continue
        relative = path.relative_to(root).as_posix()
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        extension = path.suffix.lower()
        imports, exports = _imports_and_exports(source, extension)
        files.append({"path": relative, "language": LANGUAGES[extension], "lines": source.count("\n") + 1,
                      "imports": imports, "exports": exports})
        for entity, body in _entities_for_source(source, relative, extension):
            entities.append(entity)
            bodies[entity["id"]] = body
            if len(entities) >= MAX_ENTITIES:
                break
        if len(entities) >= MAX_ENTITIES:
            break
    _link_references(entities, bodies)
    return entities, files


def _is_candidate(path: Path, root: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return False
    name = path.name.lower()
    if name.endswith((".min.js", ".d.ts", ".bundle.js")):
        return False
    if any(part in SKIP_DIRECTORIES for part in path.relative_to(root).parts[:-1]):
        return False
    return path.stat().st_size <= MAX_SOURCE_BYTES


def _entities_for_source(source: str, relative: str, extension: str) -> list[tuple[dict, str]]:
    if extension == ".py":
        return _python_entities(source, relative)
    return _brace_language_entities(source, relative, extension)


# --- Python (standard-library AST) -------------------------------------------------------
def _python_entities(source: str, relative: str) -> list[tuple[dict, str]]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    lines, found = source.splitlines(), []

    def visit(node, parent_class):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                found.append(_build(lines, relative, "class", child.name, child.lineno, child.end_lineno))
                visit(child, child.name)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "method" if parent_class else "function"
                found.append(_build(lines, relative, kind, child.name, child.lineno, child.end_lineno, parent_class))
                visit(child, None)  # functions nested inside are plain functions
            else:
                visit(child, parent_class)

    visit(tree, None)
    return found


# --- JavaScript / TypeScript / Java / C# (regex + brace matching) ------------------------
def _brace_language_entities(source: str, relative: str, extension: str) -> list[tuple[dict, str]]:
    lines, found, classes = source.splitlines(), [], []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "*", "/*", "@")):
            continue
        match = _match_declaration(lines, index, extension)
        if match is None:
            continue
        kind, name, column = match
        start, end = index + 1, _block_end(lines, index, column)
        parent = next((c_name for c_name, c_start, c_end in reversed(classes) if c_start < start <= c_end), None)
        body = "\n".join(lines[index:end])
        if kind == "class":
            if extension in JS_FAMILY and REACT_CLASS.search(line):
                kind = "component"
            classes.append((name, start, end))
        elif kind == "member":
            if parent is None:
                continue  # "name() {" outside a class is usually an object literal or statement
            kind = "method"
        elif kind == "function" and extension in JS_FAMILY and name[0].isupper() and JSX_RETURN.search(body):
            kind = "component"  # React function component: PascalCase name that returns JSX
        found.append(_build(lines, relative, kind, name, start, end, parent if kind == "method" else None))
    return found


def _match_declaration(lines: list[str], index: int, extension: str):
    """Return (kind, name, column) if this line starts a class/function/method, otherwise None.

    ``column`` is where brace matching should begin. For "const X: Type = ..." it is
    the position after "=", so braces inside a TypeScript type are not mistaken for the body.
    """
    line = lines[index]
    if extension in JS_FAMILY:
        if m := JS_CLASS.match(line):
            return "class", m.group(1), 0
        if m := JS_FUNCTION.match(line):
            return "function", m.group(1), 0
        if m := JS_VARIABLE.match(line):
            return ("function", m.group(1), m.start(2)) if _holds_function(m.group(2), lines, index) else None
        if (m := JS_METHOD.match(line)) and m.group(1) not in KEYWORDS:
            return "member", m.group(1), 0
        if (m := JS_CLASS_FIELD.match(line)) and _holds_function(m.group(2), lines, index):
            return "member", m.group(1), m.start(2)
        return None
    if m := JAVA_CLASS.match(line):
        return "class", m.group(1), 0
    if (m := JAVA_METHOD.match(line)) and m.group(1) not in KEYWORDS:
        return "member", m.group(1), 0
    return None


def _holds_function(rest: str, lines: list[str], index: int) -> bool:
    """Check whether the text after '=' is an arrow function or function expression.

    The next few lines are joined in, so multi-line parameter lists still work.
    """
    window = " ".join([rest] + [line.strip() for line in lines[index + 1:index + 6]])
    return bool(ARROW_START.match(window.strip()))


def _block_end(lines: list[str], start_index: int, start_column: int = 0) -> int:
    """Return the 1-based last line of the declaration that starts at ``lines[start_index]``.

    Walks characters while skipping strings and comments, counting brackets until
    the body's closing "}" (or the ";"/line end of a concise arrow function).
    """
    depth, body_open, concise, arrow_pending = 0, False, False, False
    quote, block_comment, previous = None, False, ""
    last = min(len(lines), start_index + MAX_BLOCK_LINES)
    for index in range(start_index, last):
        line, position = lines[index], (start_column if index == start_index else 0)
        while position < len(line):
            char = line[position]
            following = line[position + 1] if position + 1 < len(line) else ""
            if block_comment:
                if char == "*" and following == "/":
                    block_comment, position = False, position + 1
            elif quote:
                if char == "\\":
                    position += 1
                elif char == quote:
                    quote = None
            elif char == "/" and following == "/":
                break
            elif char == "/" and following == "*":
                block_comment, position = True, position + 1
            # In JSX text such as <p>Don't</p>, an apostrophe after a letter is not a string.
            elif char == "`" or (char in "'\"" and not previous.isalnum()):
                quote = char
            elif not char.isspace():
                if arrow_pending:
                    arrow_pending, concise = False, char != "{"
                if char == "=" and following == ">" and depth == 0 and not body_open:
                    arrow_pending, position = True, position + 1
                elif char in "{([":
                    if char == "{" and depth == 0 and not concise:
                        body_open = True
                    depth += 1
                elif char in "})]":
                    depth = max(depth - 1, 0)
                    if depth == 0 and body_open and char == "}":
                        return index + 1
                elif char == ";" and depth == 0:
                    return index + 1
            if not char.isspace():
                previous = char
            position += 1
        if concise and depth == 0 and quote is None and not block_comment:
            return index + 1
    return max(last, start_index + 1)


# --- Imports and exports -----------------------------------------------------------------
def _imports_and_exports(source: str, extension: str) -> tuple[list[str], list[str]]:
    imports, exports = [], []
    if extension == ".py":
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            return [], []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append("." * node.level + (node.module or ""))
        exports = _python_exports(tree)
    elif extension in JS_FAMILY:
        imports = JS_IMPORT.findall(source) + JS_REQUIRE.findall(source)
        for default, name in JS_EXPORT_DECL.findall(source):
            exports.append(f"{name} (default)" if default else name)
        for group in JS_EXPORT_LIST.findall(source):
            for item in group.split(","):
                item = item.strip()
                if item:
                    exports.append(item.split(" as ")[-1].strip())
        exports += [f"{name} (default)" for name in JS_EXPORT_DEFAULT.findall(source)]
        exports += [whole or member for whole, member in CJS_EXPORT.findall(source)]
    else:
        imports = JAVA_IMPORT.findall(source)
        exports = JAVA_EXPORT.findall(source)
    return _unique(imports)[:MAX_IMPORTS], _unique(exports)[:MAX_IMPORTS]


def _python_exports(tree: ast.Module) -> list[str]:
    for node in tree.body:  # an explicit __all__ list wins
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "__all__" for t in node.targets):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                return [item.value for item in node.value.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)]
    return [node.name for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_")]


# --- Relationships -----------------------------------------------------------------------
# "(\.)?" notes calls like obj.name(...): those only link to methods, so that
# e.g. /regex/.test(value) is not mistaken for a call to a function named test.
CALL_OR_JSX = re.compile(r"(\.\s*)?\b([A-Za-z_$][\w$]*)\s*\(|<([A-Z][\w$]*)[\s/>]")


def _link_references(entities: list[dict], bodies: dict[str, str]) -> None:
    """Fill entity['calls'] and entity['called_by'] using name matches inside each body."""
    by_name: dict[str, list[dict]] = {}
    for entity in entities:
        entity["calls"], entity["called_by"] = [], []
        if entity["name"] not in LINK_STOPLIST:
            by_name.setdefault(entity["name"], []).append(entity)
    # Classes with methods are skipped as callers; their methods already carry the links.
    containers = {(e["path"], e["parent"]) for e in entities if e["kind"] == "method"}
    for entity in entities:
        if (entity["path"], entity["name"]) in containers:
            continue
        plain, dotted = set(), set()
        for dot, call_name, jsx_name in CALL_OR_JSX.findall(bodies.get(entity["id"], "")):
            (dotted if dot else plain).add(call_name or jsx_name)
        dotted -= plain
        python_file = entity["path"].endswith(".py")  # module.function() is common in Python
        for name in sorted((plain | dotted) - {entity["name"]}):
            candidates = by_name.get(name, [])
            if name in dotted and not python_file:
                candidates = [c for c in candidates if c["kind"] == "method"]
            for target in _resolve(entity, candidates):
                if len(entity["calls"]) < MAX_LINKS:
                    entity["calls"].append(_link(target))
                if len(target["called_by"]) < MAX_LINKS:
                    target["called_by"].append(_link(entity))


def _resolve(source: dict, candidates: list[dict]) -> list[dict]:
    # Ignore the entity itself and anything nested inside it (e.g. a class's own methods).
    candidates = [c for c in candidates if c["id"] != source["id"] and not (
        c["path"] == source["path"] and source["start_line"] <= c["start_line"] <= source["end_line"])]
    same_file = [c for c in candidates if c["path"] == source["path"]]
    return same_file[:1] if same_file else candidates[:3]


def _link(entity: dict) -> dict:
    return {"id": entity["id"], "name": entity["display_name"], "path": entity["path"], "line": entity["start_line"]}


# --- Helpers -----------------------------------------------------------------------------
def _build(lines: list[str], path: str, kind: str, name: str, start: int, end: int | None,
           parent: str | None = None) -> tuple[dict, str]:
    end = max(end or start, start)
    excerpt = "\n".join(lines[start - 1:min(end, start - 1 + EXCERPT_LINES)])
    entity = {
        "id": f"{path}:{start}:{name}", "path": path, "kind": kind, "name": name,
        "display_name": f"{parent}.{name}" if parent else name, "parent": parent,
        "start_line": start, "end_line": end, "excerpt": excerpt,
    }
    return entity, "\n".join(lines[start - 1:end])


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))

# Code Archaeologist

Code Archaeologist is a learning-oriented Flask application that turns a repository's source code and Git history into understandable evidence about its evolution, contributors, and maintenance risks.

## Current stage

The application includes a responsive landing page, secure server-rendered registration/login/logout, CSRF-protected forms, SQLite persistence, a per-user dashboard, and a first working repository analysis flow. It accepts public HTTPS GitHub URLs or ZIP source archives, never runs repository code, and stores a source/file summary plus available Git history.

Saved analysis reports can also be exported as a PDF containing repository metrics, file structure, contributor activity, maintenance signals, recent commit evidence, and recommendations.

### Analysis progress and saved analyses

- Starting an analysis saves a **running** entry and runs the clone/scan in a background thread (`services/analysis_jobs.py`). The browser goes to a progress page that polls `/dashboard/<id>/status` and opens the results when they are ready. Failures show a safe message; technical details go only to the server log.
- Each user can run one analysis at a time. If the server stops mid-analysis, that entry is marked **failed** on the next start.
- The dashboard can search saved analyses by name and filter by source and status, sorted by newest, oldest, or name.
- Deleting goes through a confirmation page that lists what will be removed. Results and saved answers are deleted together; repository source code is never kept after analysis.
- Uploads over the size limit show a friendly message instead of a server error.

### Investigation assistant

- **Code questions** (about one function/component/class) and **repository questions** (contributors, risks, dependencies, activity, structure) both return *verified facts*, *hypotheses*, and *supporting evidence*: commits (linked to the timeline), files, and code (linked to the investigation page).
- With `OPENAI_API_KEY` set in `.env`, answers are written by the model from that same evidence; the key stays on the server. If the AI call fails, the rule-based answer is shown.
- Every answered question is saved under **Investigation history**; the newest 10 are included in the PDF report.

### PDF report

Includes the overview, charts (commit activity, commits per contributor, most-modified files), contributor areas, maintenance signals, most-connected code, recent commits, saved investigation answers, and recommendations.

### Code parsing and relationships

The parser (`services/code_parser.py`) reads code without running it:

- **Python**: standard-library `ast` (functions, classes, methods, imports, exports/`__all__`).
- **JavaScript / TypeScript / JSX / TSX** (`.js .mjs .cjs .jsx .ts .tsx`): function declarations, arrow functions (including multi-line parameters and TypeScript type annotations), `memo`/`forwardRef` wrappers, classes, class methods and arrow class fields. PascalCase functions that return JSX, and classes extending `React.Component`, are labelled **components**.
- **Java / C#**: classes, interfaces, enums, records and methods.
- A small brace matcher finds each entity's real end line, ignoring braces inside strings, comments and TypeScript types.
- Imports (`import`, `require`, `using`) and exports (`export`, `module.exports`, public classes) are saved per file.
- **Relationships**: each entity lists what it calls/renders and what calls it, matched by name (`save(`, `<Header />`). These are investigation hints, not a full call graph. `obj.name(...)` only links to methods.
- `node_modules`, `dist`, `build`, `.next`, `vendor`, minified files and `.d.ts` files are skipped.

### Dashboard charts

Each analysis shows Chart.js charts for commits over time (per day, week or month depending on how long the history is, with empty periods shown as gaps), commits per contributor, contributor activity over time (top 5 plus "Other contributors"), and the most frequently modified files. Analyses saved before these features were added still open, but they need to be re-run to show the new charts and relationships.

## Requirements

- Python 3.11+ (developed with Python 3.13)
- Git 2.30+

## Run locally (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env and set a strong SECRET_KEY before deployment.
python run.py
```

The launcher opens the reachable local address automatically. Create an account once the page opens.

### Simplest Windows start

Double-click `start_code_archaeologist.bat` in the project folder. On the first run it creates `.venv` and installs dependencies; later runs start the app and open the browser automatically. Keep its terminal window open while using the app.

If the launcher reports `No module named 'flask'`, double-click it again after pulling the latest project files; it now detects missing dependencies and installs them automatically.

Keep the PowerShell window running while using the website. The normal `python run.py` command deliberately disables Flask's auto-reloader because cloning repositories inside `instance/` would otherwise restart the server mid-analysis.

## Test

```powershell
python -m pytest
```

`pytest.ini` limits test discovery to `tests/`, so temporary repository copies are never collected as tests.

## Architecture

- `code_archaeologist/`: Flask application factory, routes, security helpers, and database layer.
- `code_archaeologist/services/`: repository ingestion, Git extraction (`scanner.py`), code parsing, risk detection, rule-based and optional AI explanations, and PDF reports.
- `code_archaeologist/templates/` and `static/`: vanilla HTML, CSS, and JavaScript frontend (`static/js/charts.js` draws the dashboard charts).
- `tests/`: automated application tests.

## Security notes

Passwords are stored using Werkzeug password hashes; SQL uses bound parameters; private dashboard access is session-protected; and form POSTs require a CSRF token. Future repository handling will validate URLs and archives and will never execute project code.

Repository ingestion accepts only public HTTPS GitHub URLs and ZIP files. ZIP extraction blocks path traversal and symbolic links and enforces configurable file and size limits. Repositories are cloned shallowly and are only read by GitPython; their code is never executed. Working copies are removed after their derived results are saved.

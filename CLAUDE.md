# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (activate venv first)
pip install -r requirements.txt

# Run the development server (port 5001)
python app.py

# Run all tests
pytest

# Run a single test file
pytest tests/test_auth.py

# Run a single test by name
pytest tests/test_auth.py::test_register_user
```

The app runs at `http://127.0.0.1:5001` with Flask debug mode enabled.

## Architecture

**Spendly** is a Flask + SQLite expense tracking app with server-side Jinja2 rendering and no ORM.

### Request flow

`app.py` defines all routes and renders templates from `templates/`. Templates extend `base.html`, which provides the navbar, footer, global CSS, and `main.js`. The database layer lives entirely in `database/db.py` and is expected to expose three functions:

- `get_db()` — returns a SQLite connection with `row_factory = sqlite3.Row` and `PRAGMA foreign_keys = ON`
- `init_db()` — creates tables with `CREATE TABLE IF NOT EXISTS`
- `seed_db()` — inserts sample rows for development

The SQLite file is `expense_tracker.db` (gitignored).

### Implementation steps

Placeholder routes in `app.py` are annotated with step numbers (Step 3–9). This reflects a planned build-out sequence:

1. `database/db.py` — SQLite setup
2. POST handler for `/register`
3. POST handler for `/login` + session management, `/logout`
4. `/profile`
5–6. (Session/auth middleware)
7. POST `/expenses/add`
8. GET/POST `/expenses/<id>/edit`
9. POST `/expenses/<id>/delete`

No authentication library (Flask-Login, etc.) or form library (WTForms) has been added yet — auth will use `werkzeug.security` for password hashing and Flask sessions directly.

### Templates & styles

`base.html` loads `static/css/style.css` globally. `landing.html` also loads `static/css/landing.css` via `{% block head %}`. The design system uses CSS custom properties defined at `:root` in `style.css` — always use these variables (e.g. `--accent`, `--paper`, `--ink`) rather than hardcoded colors.

Video modal logic is inline in `landing.html`; all other JS goes in `static/js/main.js`.

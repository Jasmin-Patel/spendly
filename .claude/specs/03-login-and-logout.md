# Spec: Login and Logout

## Overview
Implement session-based authentication so registered users can sign in and sign out of Spendly. This step wires `POST /login` (credential verification + session creation), converts the `GET /logout` stub into a real session-clearing handler, and adds a `secret_key` to the Flask app so the signed cookie session works. It is the gateway that makes all future protected routes possible.

## Depends on
- Step 1 — Database setup (`get_db()`, `users` table)
- Step 2 — Registration (`get_user_by_email()`, hashed passwords already stored)

## Routes
- `POST /login` — validates email/password, sets `session['user_id']` and `session['user_name']`, redirects to `/profile` on success — public
- `GET /logout` — clears the session, redirects to `/` — public (currently a stub)

The existing `GET /login` stub already renders `login.html`; it only needs a guard added (redirect to `/profile` if already logged in) and the template needs a real form.

## Database changes
No database changes. The existing `users` table and `get_user_by_email()` helper are sufficient.

## Templates
- **Modify:** `templates/login.html`
  - Add a form with `method="POST"` and `action="{{ url_for('login') }}"`
  - Fields: `email` (email input), `password` (password input)
  - Display inline error messages passed from the route
  - Show a link to the register page using `url_for('register')`

## Files to change
- `app.py`
  - Add `app.secret_key` (use a hard-coded dev string — e.g. `"spendly-dev-secret"`)
  - Add `session` to the Flask import line
  - Add `check_password_hash` to the `werkzeug.security` import
  - Upgrade `GET /login` to redirect to `/profile` when `session.get('user_id')` is set
  - Add `POST /login` handler (see rules below)
  - Replace the `GET /logout` stub with a real handler that calls `session.clear()` and redirects to `url_for('landing')`
- `templates/login.html` — add the login form and error display

## Files to create
None.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only
- Parameterised queries only — no f-strings in SQL
- Passwords verified with `werkzeug.security.check_password_hash` — never compare plaintext
- Session values to set on successful login: `session['user_id']` (integer), `session['user_name']` (string)
- `POST /login` must show a generic error on bad credentials — do **not** distinguish "email not found" from "wrong password" (prevents user enumeration)
- All templates extend `base.html`
- Use `url_for()` for every internal link — never hardcode paths
- DB logic stays in `database/db.py` — the route only calls `get_user_by_email()`
- Use CSS variables — never hardcode hex values in stylesheets
- `GET /logout` must accept only GET (no form needed) and always redirect — never render a template

## Definition of done
- [ ] Submitting correct email and password sets the session and redirects to `/profile`
- [ ] Submitting a wrong password shows a generic error on the login page without crashing
- [ ] Submitting an email that does not exist shows the same generic error
- [ ] Submitting with an empty field shows a validation error
- [ ] Visiting `GET /login` while already logged in redirects to `/profile` without showing the form
- [ ] Visiting `GET /logout` clears the session and redirects to the landing page
- [ ] After logout, visiting `GET /login` shows the login form (session is gone)
- [ ] No DB logic lives directly in `app.py`
- [ ] `secret_key` is set so the Flask session cookie is signed

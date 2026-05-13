# Spec: Registration

## Overview
Implement user registration so that new visitors can create a Spendly account. This step adds the `POST /register` handler and the two database helpers needed to check for duplicate emails and insert new users. It is the first authentication step in the roadmap and is required before login (Step 3) can be built.

## Depends on
- Step 1 — Database setup (`get_db()`, `init_db()`, `users` table)

## Routes
- `POST /register` — validates form input, creates user, redirects to login on success — public

The existing `GET /register` stub is already implemented; it only needs template changes.

## Database changes
No new tables or columns. The `users` table from Step 1 is sufficient.

Two new helpers must be added to `database/db.py`:
- `get_user_by_email(email)` — returns the row or `None`
- `create_user(name, email, password_hash)` — inserts and returns the new `id`

## Templates
- **Modify:** `templates/register.html`
  - Add a form with `method="POST"` and `action="{{ url_for('register') }}"`
  - Fields: `name` (text), `email` (email), `password` (password), `confirm_password` (password)
  - Display inline validation errors passed from the route
  - Show a link to the login page using `url_for('login')`

## Files to change
- `app.py` — add `POST /register` handler; import `generate_password_hash` from `werkzeug.security`; import `get_user_by_email`, `create_user` from `database.db`
- `database/db.py` — add `get_user_by_email()` and `create_user()`
- `templates/register.html` — add the registration form and error display

## Files to create
None.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only
- Parameterised queries only — no f-strings or `.format()` in SQL
- Passwords hashed with `werkzeug.security.generate_password_hash` before storing
- Never store plaintext passwords
- All templates extend `base.html`
- Use `url_for()` for every internal link — never hardcode paths
- DB logic stays in `database/db.py` — the route only calls helpers
- Use `abort(400)` for bad requests, not bare string returns
- Duplicate email must show a user-facing error message, not a 500
- CSS variables only — never hardcode hex values in stylesheets

## Definition of done
- [ ] Submitting valid name, email, and matching passwords creates a new row in `users`
- [ ] Password is stored as a hash, never plaintext
- [ ] Successful registration redirects to `GET /login`
- [ ] Submitting a duplicate email shows an error on the register page without crashing
- [ ] Submitting mismatched passwords shows a validation error
- [ ] Submitting with any empty field shows a validation error
- [ ] `GET /register` still renders the form correctly after the changes
- [ ] No DB logic lives directly in `app.py`

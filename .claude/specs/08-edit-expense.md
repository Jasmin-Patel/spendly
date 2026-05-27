# Spec: Edit Expense

## Overview
Step 8 replaces the `/expenses/<id>/edit` stub with a fully working edit form
that lets logged-in users correct an existing expense. The `GET` handler fetches
the expense row and pre-fills every form field with its current values; the
`POST` handler validates the submitted data and updates the row in-place, then
redirects back to the profile page. An ownership check ensures a user cannot
edit another user's expense — attempting to do so returns a 403.

## Depends on
- Step 1: Database setup (`expenses` table must exist)
- Step 3: Login and logout (`@login_required` and `session["user_id"]` must be available)
- Step 7: Add expense (same validation rules and category list apply)

## Routes
- `GET /expenses/<int:id>/edit` — render the edit form pre-filled with existing data — logged-in only
- `POST /expenses/<int:id>/edit` — validate and update the expense, then redirect to `/profile` on success or re-render with errors on failure — logged-in only

## Database changes
No new tables or columns.

Two new DB helpers must be added to `database/db.py`:
- `get_expense_by_id(expense_id)` — fetches a single expense row by its `id`; returns `None` if not found
- `update_expense(expense_id, amount, category, expense_date, description)` — updates the `amount`, `category`, `date`, and `description` columns for the given `id` using parameterised queries

## Templates
- **Create:** `templates/edit_expense.html`
  - Extends `base.html`
  - Contains a single `<form method="POST">` with fields:
    - `amount` — `<input type="number" step="0.01" min="0.01">` pre-filled with `expense.amount` (required)
    - `category` — `<select>` with options: Food, Transport, Bills, Health, Entertainment, Shopping, Other; pre-selected to `expense.category` (required)
    - `date` — `<input type="date">` pre-filled with `expense.date` (required)
    - `description` — `<input type="text">` pre-filled with `expense.description` (optional)
  - Displays a server-side error message when present (passed as `error`)
  - Uses `url_for('edit_expense', id=expense.id)` for the form `action`

## Files to change
- `app.py`
  - Replace the `edit_expense()` stub with a proper `GET`/`POST` handler:
    - `GET`: call `get_expense_by_id(id)`; `abort(404)` if not found; `abort(403)` if `expense["user_id"] != session["user_id"]`; render `edit_expense.html` with the expense
    - `POST`: same ownership checks first; read and validate form fields using the same rules as add-expense; on error re-render with message; on success call `update_expense()` and redirect to `url_for('profile')`
  - Add `@login_required` to the route
  - Import `get_expense_by_id` and `update_expense` from `database.db`
- `database/db.py`
  - Add `get_expense_by_id(expense_id)` helper
  - Add `update_expense(expense_id, amount, category, expense_date, description)` helper

## Files to create
- `templates/edit_expense.html` — the edit form template
- `static/css/edit_expense.css` — page-specific styles (may reuse add-expense styles via shared class names)

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — never f-strings or string concatenation in SQL
- Passwords hashed with werkzeug (no auth changes in this step)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- No inline styles — all styles go in `static/css/edit_expense.css`
- Ownership check: if `expense["user_id"] != session["user_id"]`, call `abort(403)` — do not redirect
- 404 check: if `get_expense_by_id(id)` returns `None`, call `abort(404)`
- Amount validation: must be convertible to `float` and greater than `0`; on failure re-render with error "Amount must be a positive number."
- Category validation: must be one of `["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]`; reject anything outside this list
- Date validation: attempt `datetime.strptime(value, "%Y-%m-%d")`; on failure re-render with error "Please enter a valid date."
- On success redirect to `url_for('profile')` — do not render a success template
- All amounts display the ₹ symbol wherever shown

## Definition of done
- [ ] `GET /expenses/<id>/edit` renders the edit form pre-filled with the expense's existing values (no longer returns a plain string)
- [ ] Every field (amount, category, date, description) is pre-populated correctly
- [ ] Submitting with all valid fields updates the expense row and redirects to `/profile`
- [ ] The updated values are visible in the transactions list on `/profile` immediately after redirect
- [ ] Submitting with a non-numeric or zero/negative amount re-renders the form with an error and does not update the row
- [ ] Submitting with an invalid category re-renders the form with an error and does not update the row
- [ ] Submitting with a malformed date re-renders the form with an error and does not update the row
- [ ] Visiting `/expenses/<id>/edit` for a non-existent expense returns 404
- [ ] Visiting `/expenses/<id>/edit` for another user's expense returns 403
- [ ] Visiting `/expenses/<id>/edit` while logged out redirects to `/login`
- [ ] All currency amounts display the ₹ symbol

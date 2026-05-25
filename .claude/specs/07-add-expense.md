# Spec: Add Expense

## Overview
Step 7 replaces the `/expenses/add` stub with a fully working form that lets
logged-in users record a new expense. Submitting the form inserts a row into the
`expenses` table and redirects back to the profile page. This is the first
write path for expense data, so it must be robust: amounts must be positive
numbers, categories must come from a fixed list, and the date must be a valid
ISO string. All validation happens server-side; the form re-renders with an
error message on failure.

## Depends on
- Step 1: Database setup (`expenses` table must exist with `user_id`, `amount`,
  `category`, `date`, `description` columns)
- Step 3: Login and logout (`@login_required` decorator and `session["user_id"]`
  must be available)

## Routes
- `GET /expenses/add` — render the blank add-expense form — logged-in only
- `POST /expenses/add` — validate and insert the expense, then redirect to
  `/profile` on success or re-render the form with errors on failure — logged-in only

## Database changes
No new tables or columns. The `expenses` table already has all required columns.

A new DB helper must be added to `database/db.py`:
- `add_expense(user_id, amount, category, date, description)` — inserts one row
  into `expenses` using parameterised queries; `description` may be `None`.

## Templates
- **Create:** `templates/add_expense.html`
  - Extends `base.html`
  - Contains a single `<form method="POST">` with fields:
    - `amount` — `<input type="number" step="0.01" min="0.01">` (required)
    - `category` — `<select>` with options: Food, Transport, Bills, Health,
      Entertainment, Shopping, Other (required)
    - `date` — `<input type="date">` defaulting to today's date (required)
    - `description` — `<input type="text">` (optional)
  - Displays a server-side error message when present (passed as `error`)
  - Uses `url_for('add_expense')` for the form `action`

## Files to change
- `app.py`
  - Replace the `add_expense()` stub with a proper `GET`/`POST` handler:
    - `GET`: render `add_expense.html` with today's date pre-filled
    - `POST`: read and validate form fields; on error re-render with message;
      on success call `add_expense()` DB helper and redirect to `url_for('profile')`
  - Add `@login_required` to the route
  - Import `add_expense` from `database.db`
- `database/db.py`
  - Add `add_expense(user_id, amount, category, date, description)` helper

## Files to create
- `templates/add_expense.html` — the add-expense form template
- `static/css/add_expense.css` — page-specific styles for the form

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — never f-strings or string concatenation in SQL
- Passwords hashed with werkzeug (no auth changes in this step)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- No inline styles — all styles go in `static/css/add_expense.css`
- Amount validation: must be convertible to `float` and greater than `0`; on
  failure, re-render form with error "Amount must be a positive number."
- Category validation: must be one of the fixed list
  `["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]`;
  reject anything outside this list
- Date validation: attempt `datetime.strptime(value, "%Y-%m-%d")`; on failure,
  re-render with error "Please enter a valid date."
- On success, redirect to `url_for('profile')` — do not render a success template
- The `GET` handler must pre-fill the `date` field with `date.today().isoformat()`
- All amounts must display the ₹ symbol wherever shown

## Definition of done
- [ ] `GET /expenses/add` renders the add-expense form (no longer returns a plain string)
- [ ] The date field defaults to today's date when the form first loads
- [ ] Submitting the form with all valid fields inserts the expense and redirects
  to `/profile`
- [ ] The new expense appears in the transactions list on `/profile` immediately
  after redirect
- [ ] Submitting with a non-numeric or zero/negative amount re-renders the form
  with an error message and does not insert a row
- [ ] Submitting with an empty or invalid category re-renders the form with an
  error and does not insert a row
- [ ] Submitting with a malformed date re-renders the form with an error and
  does not insert a row
- [ ] Description is optional — submitting without it succeeds
- [ ] Visiting `/expenses/add` while logged out redirects to `/login`
- [ ] All currency amounts display the ₹ symbol

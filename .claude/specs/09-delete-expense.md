# Spec: Delete Expense

## Overview
Step 9 replaces the `/expenses/<id>/delete` stub with a fully working delete
handler that lets logged-in users permanently remove one of their own expenses.
There is no separate confirmation page — the delete action is triggered by a
`POST` form in the profile and edit pages, with a browser `confirm()` dialog as
a lightweight guard against accidental clicks. An ownership check prevents a
user from deleting another user's expense; attempting to do so returns a 403.

## Depends on
- Step 1: Database setup (`expenses` table must exist)
- Step 3: Login and logout (`@login_required` and `session["user_id"]` must be available)
- Step 4/5: Profile page (transaction list is where the delete button lives)
- Step 8: Edit expense (`edit_expense.html` should also offer a delete button)

## Routes
- `POST /expenses/<int:expense_id>/delete` — verify ownership, delete the row,
  redirect to `/profile` — logged-in only

No `GET` handler is needed; visiting the URL directly via the browser address
bar should return 405 Method Not Allowed.

## Database changes
No new tables or columns.

One new DB helper must be added to `database/db.py`:
- `delete_expense(expense_id, user_id)` — deletes the row matching both `id`
  and `user_id`; returns `True` if a row was deleted, `False` otherwise.

## Templates
- **Modify:** `templates/profile.html`
  - Add a delete `<form>` inline next to the existing Edit link for each
    transaction row:
    ```html
    <form method="POST"
          action="{{ url_for('delete_expense', expense_id=tx['id']) }}"
          class="profile-tx-delete-form"
          onsubmit="return confirm('Delete this expense?')">
        <button type="submit" class="profile-tx-delete">Delete</button>
    </form>
    ```
- **Modify:** `templates/edit_expense.html`
  - Add a delete `<form>` below the edit form so users can delete directly
    from the edit page:
    ```html
    <form method="POST"
          action="{{ url_for('delete_expense', expense_id=expense.id) }}"
          class="delete-form"
          onsubmit="return confirm('Delete this expense?')">
        <button type="submit" class="btn-danger">Delete expense</button>
    </form>
    ```

## Files to change
- `app.py`
  - Replace the `delete_expense()` stub:
    - Change route parameter from `id` to `expense_id` for consistency with
      `edit_expense`
    - Add `methods=["POST"]` to the route decorator
    - Add `@login_required`
    - Call `get_expense_by_id(expense_id)`; `abort(404)` if `None`
    - `abort(403)` if `expense["user_id"] != session["user_id"]`
    - Call `delete_expense(expense_id, session["user_id"])`
    - Redirect to `url_for("profile")`
  - Import `delete_expense` from `database.db`
- `database/db.py`
  - Add `delete_expense(expense_id, user_id)` helper
- `templates/profile.html`
  - Add inline delete form next to each transaction's Edit link
- `templates/edit_expense.html`
  - Add inline delete form below the edit form

## Files to create
No new files.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — never f-strings or string concatenation in SQL
- Passwords hashed with werkzeug (no auth changes in this step)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- The route must be `POST` only — delete via `GET` is an anti-pattern; the
  stub's lack of `methods` must be corrected
- Ownership check: if `expense["user_id"] != session["user_id"]`, call
  `abort(403)` — do not redirect silently
- 404 check: if `get_expense_by_id(expense_id)` returns `None`, call
  `abort(404)`
- No new CSS files are required; style the delete button with a new rule
  in an existing CSS file (e.g. `static/css/style.css` or
  `static/css/edit_expense.css`)
- The `confirm()` dialog is the only confirmation mechanism — no separate
  confirmation page
- On success redirect to `url_for('profile')` — do not render a success
  template

## Definition of done
- [ ] `POST /expenses/<id>/delete` deletes the expense and redirects to
  `/profile`; the deleted row no longer appears in the transactions list
- [ ] A Delete button/link is visible next to each transaction row on the
  profile page
- [ ] A Delete button is visible on the edit-expense page
- [ ] Clicking Delete triggers a browser `confirm()` dialog before submitting
- [ ] Visiting `GET /expenses/<id>/delete` returns 405 (Method Not Allowed)
- [ ] Attempting to delete a non-existent expense returns 404
- [ ] Attempting to delete another user's expense returns 403
- [ ] Visiting the route while logged out redirects to `/login`

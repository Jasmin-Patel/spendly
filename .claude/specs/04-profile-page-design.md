# Spec: Profile Page Design

## Overview
The profile page is the first protected route in Spendly. It gives authenticated users a personal hub showing their account details (name, email, member since) alongside a high-level spending snapshot drawn from the existing expenses table. This step also introduces a reusable `login_required` decorator in `app.py` that all future authenticated routes (Steps 7–9) will use, replacing the ad-hoc `session.get("user_id")` checks that would otherwise be duplicated across every protected route.

## Depends on
- **Step 01** — database setup (`users` and `expenses` tables, `get_db()`)
- **Step 02** — user registration (`create_user`, `get_user_by_email`)
- **Step 03** — login/logout (session set/cleared, `/login` and `/logout` routes)

## Routes
- `GET /profile` — renders the authenticated user's profile page — logged-in only

## Database changes
No new tables or columns. Two new query helpers must be added to `database/db.py`:

- `get_user_by_id(user_id)` — fetches a single user row by primary key; used by the profile route to get fresh data (name, email, created_at) rather than relying solely on session values.
- `get_expense_summary(user_id)` — returns a dict with:
  - `total_count` — total number of expenses for the user
  - `total_amount` — sum of all expense amounts (REAL), 0.0 if none
  - `top_category` — the category with the highest total spend, `None` if no expenses

Both use parameterised queries (`?` placeholders). No schema changes are required.

## Templates
- **Create:** `templates/profile.html` — extends `base.html`; displays user info card and spending snapshot section
- **Modify:** none

## Files to change
- `app.py` — add `login_required` decorator; implement `GET /profile` route
- `database/db.py` — add `get_user_by_id()` and `get_expense_summary()` helpers

## Files to create
- `templates/profile.html`
- `static/css/profile.css`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only
- Parameterised queries only — never f-strings or `.format()` in SQL
- Passwords are never re-read or displayed — only name, email, created_at from the users table
- Use CSS variables — never hardcode hex values in `profile.css`
- All templates extend `base.html`
- The `login_required` decorator must redirect to `url_for("login")`, not a hardcoded string
- The `/profile` route function must do nothing except call helpers, pass data to the template, and call `render_template()` — no inline SQL
- Format `created_at` into a human-readable string (e.g. "14 May 2026") in the route before passing to the template
- All currency amounts must use the ₹ symbol (INR), not $

## Definition of done
- [ ] Visiting `/profile` while logged out redirects to `/login`
- [ ] Visiting `/profile` while logged in renders `profile.html` with the correct name and email
- [ ] The "Member since" date is displayed in a readable format (e.g. "14 May 2026")
- [ ] Total expense count and total amount (₹) are displayed on the page
- [ ] Top spending category is shown, or a "No expenses yet" fallback is shown when there are none
- [ ] The `login_required` decorator is defined in `app.py` and applied to the `/profile` route
- [ ] All internal links on the profile page use `url_for()`
- [ ] `profile.css` is linked from `profile.html` and contains no hardcoded hex colours
- [ ] `get_user_by_id()` and `get_expense_summary()` are defined in `database/db.py` and use `?` placeholders

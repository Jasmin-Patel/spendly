"""
Tests for Step 8 — Edit Expense feature.

Spec: .claude/specs/08-edit-expense.md

Design notes
------------
- Reuses the session-scoped `app` and function-scoped `client` fixtures from
  conftest.py.  The real file-based spendly.db is used (same pattern as
  test_07), so every test that writes data cleans up via teardown_method.
- `_register_and_login` creates a fresh user per test via the route, keeping
  the session cookie bound to that user.
- `_seed_expense` inserts a known expense directly into the DB so tests have a
  deterministic expense ID to edit.
- Each test class tears down its own users and expenses; no inter-test deps.
- PAST_DATE is a fixed historical ISO date that will never be affected by any
  date-filter preset logic in the profile route.
"""

import uuid

import pytest
from werkzeug.security import generate_password_hash

from database.db import get_db


# ------------------------------------------------------------------ #
# Constants                                                           #
# ------------------------------------------------------------------ #

VALID_CATEGORIES = [
    "Food", "Transport", "Bills", "Health",
    "Entertainment", "Shopping", "Other",
]

PAST_DATE = "2021-06-15"
ANOTHER_DATE = "2020-03-10"


# ------------------------------------------------------------------ #
# DB helpers                                                          #
# ------------------------------------------------------------------ #

def _unique_email():
    return f"edit_exp_{uuid.uuid4().hex[:8]}@test.com"


def _register_and_login(client, email, password="Testpass1!"):
    """Register a fresh user through the route and log them in.
    Returns the DB id of the created user."""
    client.post(
        "/register",
        data={
            "name": "Edit Tester",
            "email": email,
            "password": password,
            "confirm_password": password,
        },
        follow_redirects=False,
    )
    client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    conn = get_db()
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return row["id"] if row else None


def _seed_expense(user_id, amount=99.99, category="Food",
                  expense_date=PAST_DATE, description="Original desc"):
    """Insert one expense row directly into the DB. Returns the new expense id."""
    conn = get_db()
    conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description)"
        " VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, category, expense_date, description),
    )
    conn.commit()
    expense_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return expense_id


def _get_expense_row(expense_id):
    """Fetch a single expense row from the DB by id."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM expenses WHERE id = ?", (expense_id,)
    ).fetchone()
    conn.close()
    return row


def _delete_expenses_for_user(user_id):
    conn = get_db()
    conn.execute("DELETE FROM expenses WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def _delete_user(user_id):
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


def _create_user_direct(name, email, password="Testpass1!"):
    """Insert a user directly into the DB (no session side-effect).
    Returns the new user id."""
    conn = get_db()
    conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (name, email, generate_password_hash(password)),
    )
    conn.commit()
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return user_id


# ------------------------------------------------------------------ #
# Auth guard                                                          #
# ------------------------------------------------------------------ #

class TestEditExpenseAuthGuard:
    """
    Both GET and POST /expenses/<id>/edit must redirect unauthenticated
    users to /login with a 302.
    """

    def test_get_unauthenticated_redirects_to_login(self, client):
        response = client.get("/expenses/9999/edit")
        assert response.status_code == 302, (
            "GET /expenses/<id>/edit without login must return 302"
        )
        assert "/login" in response.headers["Location"], (
            "Unauthenticated GET must redirect to /login"
        )

    def test_post_unauthenticated_redirects_to_login(self, client):
        response = client.post(
            "/expenses/9999/edit",
            data={
                "amount": "50.00",
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert response.status_code == 302, (
            "POST /expenses/<id>/edit without login must return 302"
        )
        assert "/login" in response.headers["Location"], (
            "Unauthenticated POST must redirect to /login"
        )

    def test_get_unauthenticated_follow_redirects_lands_on_login_page(self, client):
        response = client.get("/expenses/9999/edit", follow_redirects=True)
        assert b"login" in response.data.lower() or b"Login" in response.data, (
            "Following the redirect from unauthenticated GET must land on login page"
        )


# ------------------------------------------------------------------ #
# 404 — non-existent expense id                                       #
# ------------------------------------------------------------------ #

class TestEditExpense404:
    """
    GET and POST for an expense id that does not exist must return 404.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    def test_get_nonexistent_id_returns_404(self, client):
        self.user_id = _register_and_login(client, self.email)
        response = client.get("/expenses/999999/edit")
        assert response.status_code == 404, (
            "GET /expenses/<nonexistent-id>/edit must return 404"
        )

    def test_post_nonexistent_id_returns_404(self, client):
        self.user_id = _register_and_login(client, self.email)
        response = client.post(
            "/expenses/999999/edit",
            data={
                "amount": "50.00",
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert response.status_code == 404, (
            "POST /expenses/<nonexistent-id>/edit must return 404"
        )


# ------------------------------------------------------------------ #
# 403 — ownership check                                               #
# ------------------------------------------------------------------ #

class TestEditExpenseOwnershipCheck:
    """
    GET and POST for an expense owned by a different user must return 403.
    The logged-in user must NOT be able to edit another user's expense.
    """

    def setup_method(self):
        # The currently logged-in user
        self.owner_email = _unique_email()
        self.attacker_email = _unique_email()
        self.owner_id = None
        self.attacker_id = None
        self.expense_id = None

    def teardown_method(self):
        for uid in [self.owner_id, self.attacker_id]:
            if uid:
                _delete_expenses_for_user(uid)
                _delete_user(uid)

    def _setup_two_users(self, client):
        """Create owner with an expense, then log in as attacker."""
        # Create owner directly in DB (no session side-effect)
        self.owner_id = _create_user_direct("Owner User", self.owner_email)
        self.expense_id = _seed_expense(self.owner_id)
        # Log in as attacker via the route
        self.attacker_id = _register_and_login(client, self.attacker_email)

    def test_get_other_users_expense_returns_403(self, client):
        self._setup_two_users(client)
        response = client.get(f"/expenses/{self.expense_id}/edit")
        assert response.status_code == 403, (
            "GET /expenses/<other-user-expense>/edit must return 403"
        )

    def test_post_other_users_expense_returns_403(self, client):
        self._setup_two_users(client)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "1.00",
                "category": "Food",
                "date": PAST_DATE,
                "description": "hijack",
            },
        )
        assert response.status_code == 403, (
            "POST /expenses/<other-user-expense>/edit must return 403"
        )

    def test_post_other_users_expense_does_not_modify_db(self, client):
        """Even when the POST is blocked with 403, the expense row must be unchanged."""
        self._setup_two_users(client)
        original = _get_expense_row(self.expense_id)
        client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "1.00",
                "category": "Food",
                "date": PAST_DATE,
                "description": "hijacked",
            },
        )
        after = _get_expense_row(self.expense_id)
        assert after["amount"] == original["amount"], (
            "403 POST must not modify the expense amount"
        )
        assert after["description"] == original["description"], (
            "403 POST must not modify the expense description"
        )


# ------------------------------------------------------------------ #
# GET /expenses/<id>/edit — happy path                                #
# ------------------------------------------------------------------ #

class TestGetEditExpense:
    """
    GET /expenses/<id>/edit for the authenticated owner must render the
    edit form pre-filled with the expense's current values.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None
        self.expense_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    def test_get_returns_200(self, client):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.get(f"/expenses/{self.expense_id}/edit")
        assert response.status_code == 200, (
            "GET /expenses/<id>/edit must return 200 for the owner"
        )

    def test_get_no_longer_returns_stub_string(self, client):
        """Route must render a template, not the old stub string."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.get(f"/expenses/{self.expense_id}/edit")
        assert b"coming in Step" not in response.data, (
            "Stub string must be replaced with a real template"
        )

    def test_get_renders_form_element(self, client):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.get(f"/expenses/{self.expense_id}/edit")
        assert b"<form" in response.data, (
            "Edit expense page must contain a <form> element"
        )

    def test_get_form_has_amount_field(self, client):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.get(f"/expenses/{self.expense_id}/edit")
        assert b'name="amount"' in response.data, (
            "Form must have an amount input field"
        )

    def test_get_form_has_category_field(self, client):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.get(f"/expenses/{self.expense_id}/edit")
        assert b'name="category"' in response.data, (
            "Form must have a category select field"
        )

    def test_get_form_has_date_field(self, client):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.get(f"/expenses/{self.expense_id}/edit")
        assert b'name="date"' in response.data, (
            "Form must have a date input field"
        )

    def test_get_form_has_description_field(self, client):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.get(f"/expenses/{self.expense_id}/edit")
        assert b'name="description"' in response.data, (
            "Form must have a description input field"
        )

    def test_get_prefills_amount(self, client):
        """The current amount value must appear somewhere in the form response."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id, amount=123.45)
        response = client.get(f"/expenses/{self.expense_id}/edit")
        # The amount can be rendered as "123.45" or "123.450…" — check the integer part
        assert b"123" in response.data, (
            "Pre-filled amount must appear in the GET response"
        )

    def test_get_prefills_category(self, client):
        """The current category must appear pre-selected in the response."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id, category="Transport")
        response = client.get(f"/expenses/{self.expense_id}/edit")
        assert b"Transport" in response.data, (
            "Pre-filled category 'Transport' must appear in the GET response"
        )

    def test_get_prefills_date(self, client):
        """The current date must appear pre-filled in the response."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id, expense_date="2020-11-30")
        response = client.get(f"/expenses/{self.expense_id}/edit")
        assert b"2020-11-30" in response.data, (
            "Pre-filled date '2020-11-30' must appear in the GET response"
        )

    def test_get_prefills_description(self, client):
        """The current description must appear pre-filled in the response."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id, description="My coffee run")
        response = client.get(f"/expenses/{self.expense_id}/edit")
        assert b"My coffee run" in response.data, (
            "Pre-filled description must appear in the GET response"
        )

    def test_get_contains_all_valid_categories(self, client):
        """All seven valid categories must appear as options."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.get(f"/expenses/{self.expense_id}/edit")
        for category in VALID_CATEGORIES:
            assert category.encode() in response.data, (
                f"Category '{category}' must appear as an option"
            )

    def test_get_shows_rupee_symbol(self, client):
        """The edit-expense form must display the ₹ symbol."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.get(f"/expenses/{self.expense_id}/edit")
        assert "₹".encode() in response.data, (
            "The edit-expense page must contain the ₹ symbol"
        )

    def test_get_extends_base_template(self, client):
        """Page must use base.html layout — check for the app name in nav."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.get(f"/expenses/{self.expense_id}/edit")
        assert b"Spendly" in response.data, (
            "Page must extend base.html (Spendly nav expected)"
        )

    def test_get_has_no_error_message_on_first_load(self, client):
        """A fresh GET must not display any validation error message."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.get(f"/expenses/{self.expense_id}/edit")
        assert b"must be a positive number" not in response.data, (
            "No amount error must appear on a fresh GET"
        )
        assert b"Please enter a valid date" not in response.data, (
            "No date error must appear on a fresh GET"
        )
        assert b"valid category" not in response.data.lower(), (
            "No category error must appear on a fresh GET"
        )

    def test_get_uses_post_method_in_form(self, client):
        """The form's method attribute must be POST."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.get(f"/expenses/{self.expense_id}/edit")
        assert b'method="POST"' in response.data or b"method='POST'" in response.data \
               or b'method="post"' in response.data or b"method='post'" in response.data, (
            "The form must use POST method"
        )


# ------------------------------------------------------------------ #
# POST /expenses/<id>/edit — happy path                               #
# ------------------------------------------------------------------ #

class TestPostEditExpenseHappyPath:
    """
    A valid POST must update the expense in the DB and redirect to /profile.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None
        self.expense_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    def test_valid_post_redirects_to_profile(self, client):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "55.00",
                "category": "Transport",
                "date": ANOTHER_DATE,
                "description": "Updated desc",
            },
        )
        assert response.status_code == 302, (
            "Successful POST must return 302"
        )
        assert "/profile" in response.headers["Location"], (
            "Redirect target must be /profile"
        )

    def test_valid_post_updates_amount_in_db(self, client):
        """DB side effect: amount column must hold the new value."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id, amount=10.00)
        client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "250.00",
                "category": "Bills",
                "date": PAST_DATE,
                "description": "Updated bill",
            },
        )
        row = _get_expense_row(self.expense_id)
        assert abs(row["amount"] - 250.00) < 0.001, (
            "Amount in DB must be updated to 250.00"
        )

    def test_valid_post_updates_category_in_db(self, client):
        """DB side effect: category column must hold the new value."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id, category="Food")
        client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "99.99",
                "category": "Health",
                "date": PAST_DATE,
                "description": "Doctor visit",
            },
        )
        row = _get_expense_row(self.expense_id)
        assert row["category"] == "Health", (
            "Category in DB must be updated to 'Health'"
        )

    def test_valid_post_updates_date_in_db(self, client):
        """DB side effect: date column must hold the new value."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id, expense_date=PAST_DATE)
        client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "30.00",
                "category": "Shopping",
                "date": "2019-08-22",
                "description": "Clothes",
            },
        )
        row = _get_expense_row(self.expense_id)
        assert row["date"] == "2019-08-22", (
            "Date in DB must be updated to '2019-08-22'"
        )

    def test_valid_post_updates_description_in_db(self, client):
        """DB side effect: description column must hold the new value."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id, description="Old desc")
        client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "45.00",
                "category": "Entertainment",
                "date": PAST_DATE,
                "description": "New desc XYZ",
            },
        )
        row = _get_expense_row(self.expense_id)
        assert row["description"] == "New desc XYZ", (
            "Description in DB must be updated to 'New desc XYZ'"
        )

    def test_valid_post_updates_all_fields_in_db(self, client):
        """All four editable fields must be updated atomically in one POST."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(
            self.user_id,
            amount=1.00,
            category="Food",
            expense_date=PAST_DATE,
            description="before",
        )
        client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "777.77",
                "category": "Other",
                "date": "2018-01-01",
                "description": "after",
            },
        )
        row = _get_expense_row(self.expense_id)
        assert abs(row["amount"] - 777.77) < 0.001, "Amount not updated"
        assert row["category"] == "Other", "Category not updated"
        assert row["date"] == "2018-01-01", "Date not updated"
        assert row["description"] == "after", "Description not updated"

    def test_valid_post_updated_expense_visible_on_profile(self, client):
        """After redirect to /profile, the updated description must be visible."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id, description="BeforeEdit")
        client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "88.00",
                "category": "Food",
                "date": PAST_DATE,
                "description": "AfterEditUnique9q7",
            },
            follow_redirects=False,
        )
        profile_response = client.get("/profile")
        assert b"AfterEditUnique9q7" in profile_response.data, (
            "Updated expense description must appear on /profile after edit"
        )

    def test_description_optional_post_succeeds(self, client):
        """Submitting without a description must succeed and redirect."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id, description="Has desc")
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "60.00",
                "category": "Food",
                "date": PAST_DATE,
                "description": "",
            },
        )
        assert response.status_code == 302, (
            "POST without description must return 302"
        )
        assert "/profile" in response.headers["Location"], (
            "POST without description must redirect to /profile"
        )

    def test_description_optional_stores_null_or_empty(self, client):
        """When description is omitted, the DB row must store NULL (not the old value)."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id, description="Has desc")
        client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "60.00",
                "category": "Food",
                "date": PAST_DATE,
                "description": "",
            },
        )
        row = _get_expense_row(self.expense_id)
        assert row["description"] is None or row["description"] == "", (
            "Empty description must be stored as NULL or empty string, not the original value"
        )

    @pytest.mark.parametrize("category", VALID_CATEGORIES)
    def test_each_valid_category_accepted(self, client, category):
        """Every category in the fixed list must be accepted without error."""
        email = _unique_email()
        user_id = _register_and_login(client, email)
        expense_id = _seed_expense(user_id)
        try:
            response = client.post(
                f"/expenses/{expense_id}/edit",
                data={
                    "amount": "10.00",
                    "category": category,
                    "date": PAST_DATE,
                    "description": f"Test {category}",
                },
            )
            assert response.status_code == 302, (
                f"Category '{category}' must be accepted and redirect"
            )
        finally:
            _delete_expenses_for_user(user_id)
            _delete_user(user_id)


# ------------------------------------------------------------------ #
# POST /expenses/<id>/edit — amount validation                        #
# ------------------------------------------------------------------ #

class TestEditExpenseAmountValidation:
    """
    Invalid or non-positive amounts must re-render the form (200) with
    "Amount must be a positive number." and must NOT update the DB row.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None
        self.expense_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    @pytest.mark.parametrize("bad_amount", [
        "abc",
        "zero",
        "",
        "   ",
        "--5",
    ])
    def test_non_numeric_amount_rerenders_form(self, client, bad_amount):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": bad_amount,
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert response.status_code == 200, (
            f"Non-numeric amount '{bad_amount}' must re-render the form (200)"
        )
        assert b"Amount must be a positive number" in response.data, (
            f"Error message must appear for amount='{bad_amount}'"
        )

    @pytest.mark.parametrize("bad_amount", [
        "abc",
        "",
        "   ",
    ])
    def test_non_numeric_amount_does_not_update_db(self, client, bad_amount):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id, amount=99.99)
        client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": bad_amount,
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        row = _get_expense_row(self.expense_id)
        assert abs(row["amount"] - 99.99) < 0.001, (
            f"DB amount must remain unchanged for non-numeric amount='{bad_amount}'"
        )

    def test_zero_amount_rerenders_with_error(self, client):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "0",
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert response.status_code == 200, (
            "Zero amount must re-render the form (200)"
        )
        assert b"Amount must be a positive number" in response.data, (
            "Error message must appear for amount=0"
        )

    def test_zero_amount_does_not_update_db(self, client):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id, amount=50.00)
        client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "0",
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        row = _get_expense_row(self.expense_id)
        assert abs(row["amount"] - 50.00) < 0.001, (
            "Amount must remain 50.00 when zero is submitted"
        )

    def test_zero_decimal_amount_rerenders_with_error(self, client):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "0.00",
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert response.status_code == 200, (
            "Amount 0.00 must re-render the form"
        )
        assert b"Amount must be a positive number" in response.data, (
            "Error message must appear for amount=0.00"
        )

    def test_negative_amount_rerenders_with_error(self, client):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "-10.00",
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert response.status_code == 200, (
            "Negative amount must re-render the form"
        )
        assert b"Amount must be a positive number" in response.data, (
            "Error message must appear for negative amount"
        )

    def test_negative_amount_does_not_update_db(self, client):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id, amount=75.00)
        client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "-99.99",
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        row = _get_expense_row(self.expense_id)
        assert abs(row["amount"] - 75.00) < 0.001, (
            "DB amount must remain 75.00 when negative amount is submitted"
        )

    def test_amount_error_rerender_still_has_form(self, client):
        """On amount error, the form element must still be present."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "bad",
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert b"<form" in response.data, (
            "Form element must still be present on amount error re-render"
        )

    def test_amount_error_rerender_still_has_category_options(self, client):
        """On amount error, category dropdown options must still be present."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "bad",
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        for category in VALID_CATEGORIES:
            assert category.encode() in response.data, (
                f"Category '{category}' must still appear in error re-render"
            )


# ------------------------------------------------------------------ #
# POST /expenses/<id>/edit — category validation                      #
# ------------------------------------------------------------------ #

class TestEditExpenseCategoryValidation:
    """
    Categories outside the fixed list must re-render the form (200) with
    an error and must NOT update the DB row.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None
        self.expense_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    @pytest.mark.parametrize("bad_category", [
        "",
        "Groceries",
        "food",
        "FOOD",
        "Food ",
        " Food",
        "InvalidCategory",
        "<script>alert(1)</script>",
    ])
    def test_invalid_category_rerenders_form(self, client, bad_category):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id, category="Food")
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "50.00",
                "category": bad_category,
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert response.status_code == 200, (
            f"Invalid category '{bad_category}' must re-render the form (200)"
        )

    @pytest.mark.parametrize("bad_category", [
        "",
        "Groceries",
        "food",
    ])
    def test_invalid_category_shows_error_message(self, client, bad_category):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id, category="Food")
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "50.00",
                "category": bad_category,
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert (
            b"valid category" in response.data.lower()
            or b"Please select" in response.data
        ), (
            f"Error message must appear for invalid category '{bad_category}'"
        )

    @pytest.mark.parametrize("bad_category", [
        "",
        "Groceries",
        "food",
    ])
    def test_invalid_category_does_not_update_db(self, client, bad_category):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id, category="Food")
        client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "50.00",
                "category": bad_category,
                "date": PAST_DATE,
                "description": "test",
            },
        )
        row = _get_expense_row(self.expense_id)
        assert row["category"] == "Food", (
            f"Category must remain 'Food' when invalid category '{bad_category}' is submitted"
        )


# ------------------------------------------------------------------ #
# POST /expenses/<id>/edit — date validation                          #
# ------------------------------------------------------------------ #

class TestEditExpenseDateValidation:
    """
    Malformed or missing dates must re-render the form (200) with
    "Please enter a valid date." and must NOT update the DB row.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None
        self.expense_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    @pytest.mark.parametrize("bad_date", [
        "",
        "not-a-date",
        "15-06-2021",
        "06/15/2021",
        "20210615",
        "2021-13-01",
        "2021-06-32",
        "2021-02-30",
        "2021-6-15",
        "2021-06-1",
        "2021-06-15T00:00:00",
        "tomorrow",
    ])
    def test_malformed_date_rerenders_form(self, client, bad_date):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "50.00",
                "category": "Food",
                "date": bad_date,
                "description": "test",
            },
        )
        assert response.status_code == 200, (
            f"Malformed date '{bad_date}' must re-render the form (200)"
        )

    @pytest.mark.parametrize("bad_date", [
        "",
        "not-a-date",
        "15-06-2021",
        "2021-13-01",
    ])
    def test_malformed_date_shows_error_message(self, client, bad_date):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "50.00",
                "category": "Food",
                "date": bad_date,
                "description": "test",
            },
        )
        assert b"Please enter a valid date" in response.data, (
            f"Error 'Please enter a valid date.' must appear for date='{bad_date}'"
        )

    @pytest.mark.parametrize("bad_date", [
        "",
        "not-a-date",
        "15-06-2021",
        "2021-13-01",
    ])
    def test_malformed_date_does_not_update_db(self, client, bad_date):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id, expense_date=PAST_DATE)
        client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "50.00",
                "category": "Food",
                "date": bad_date,
                "description": "test",
            },
        )
        row = _get_expense_row(self.expense_id)
        assert row["date"] == PAST_DATE, (
            f"Date must remain '{PAST_DATE}' when malformed date '{bad_date}' is submitted"
        )


# ------------------------------------------------------------------ #
# POST — error re-render preserves form structure                     #
# ------------------------------------------------------------------ #

class TestEditExpenseErrorRerender:
    """
    On any validation error the form must be re-rendered (not redirected),
    still contain a <form>, the category options, and the ₹ symbol.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None
        self.expense_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    def test_amount_error_rerender_not_redirect(self, client):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "bad",
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert response.status_code == 200, (
            "Amount validation error must return 200, not redirect"
        )

    def test_category_error_rerender_not_redirect(self, client):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "30.00",
                "category": "NotACategory",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert response.status_code == 200, (
            "Category validation error must return 200, not redirect"
        )

    def test_date_error_rerender_not_redirect(self, client):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "30.00",
                "category": "Food",
                "date": "not-a-date",
                "description": "test",
            },
        )
        assert response.status_code == 200, (
            "Date validation error must return 200, not redirect"
        )

    def test_error_rerender_still_has_rupee_symbol(self, client):
        """The ₹ symbol must be present even on error re-renders."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "-1",
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert "₹".encode() in response.data, (
            "₹ symbol must be present on the error re-render page"
        )

    def test_error_rerender_still_has_form_element(self, client):
        """The <form> element must still be present on error re-renders."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "bad",
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert b"<form" in response.data, (
            "<form> must still appear in the error re-render"
        )

    def test_error_rerender_still_has_all_category_options(self, client):
        """All category options must be present in the error re-render."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "bad",
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        for category in VALID_CATEGORIES:
            assert category.encode() in response.data, (
                f"Category '{category}' must still appear in error re-render"
            )


# ------------------------------------------------------------------ #
# Edge cases                                                          #
# ------------------------------------------------------------------ #

class TestEditExpenseEdgeCases:
    """
    Edge cases: minimal positive amount, large amount, SQL injection in
    description, very long description.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None
        self.expense_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    def test_minimal_positive_amount_accepted(self, client):
        """0.01 — the smallest valid positive amount — must be accepted."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id, amount=50.00)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "0.01",
                "category": "Food",
                "date": PAST_DATE,
                "description": "minimum amount edit",
            },
        )
        assert response.status_code == 302, (
            "Amount 0.01 must be accepted and redirect"
        )
        row = _get_expense_row(self.expense_id)
        assert abs(row["amount"] - 0.01) < 0.001, (
            "0.01 must be stored in the DB after edit"
        )

    def test_large_amount_accepted(self, client):
        """A large but valid amount must be stored correctly."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "99999.99",
                "category": "Bills",
                "date": PAST_DATE,
                "description": "large expense",
            },
        )
        assert response.status_code == 302, (
            "Large amount must be accepted"
        )

    def test_sql_injection_in_description_is_safe(self, client):
        """
        SQL injection in description must be stored literally (parameterized
        queries protect against this). The expense row must still exist.
        """
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        injection = "'); DROP TABLE expenses; --"
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "5.00",
                "category": "Other",
                "date": PAST_DATE,
                "description": injection,
            },
        )
        assert response.status_code == 302, (
            "SQL injection in description must be handled safely"
        )
        row = _get_expense_row(self.expense_id)
        assert row is not None, (
            "Expense row must still exist after SQL injection attempt"
        )
        assert row["description"] == injection, (
            "Injection string must be stored as a literal value"
        )

    def test_very_long_description_accepted(self, client):
        """A description of 500 characters must not cause an error."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        long_desc = "x" * 500
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "10.00",
                "category": "Other",
                "date": PAST_DATE,
                "description": long_desc,
            },
        )
        assert response.status_code == 302, (
            "Very long description must not cause a server error"
        )

    def test_whitespace_only_description_treated_as_absent(self, client):
        """
        A description of only whitespace must be treated as absent
        (feature succeeds — description is optional).
        """
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "20.00",
                "category": "Food",
                "date": PAST_DATE,
                "description": "   ",
            },
        )
        assert response.status_code == 302, (
            "Whitespace-only description must not block a valid edit submission"
        )

    def test_amount_with_many_decimal_places_accepted(self, client):
        """
        An amount with many decimal places (e.g. 10.123456) must be accepted
        as it converts to a valid positive float.
        """
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(
            f"/expenses/{self.expense_id}/edit",
            data={
                "amount": "10.123456",
                "category": "Food",
                "date": PAST_DATE,
                "description": "many decimals",
            },
        )
        assert response.status_code == 302, (
            "Amount with many decimal places must be accepted"
        )

"""
Tests for Step 7 — Add Expense feature.

Spec: .claude/specs/07-add-expense.md

Design notes
------------
- Uses the session-scoped `app` and function-scoped `client` fixtures from
  conftest.py.  The real file-based spendly.db is used (same pattern as
  test_06), so every test that writes data cleans up in teardown.
- `_register_and_login` creates a fresh user per test via the route so the
  session cookie matches the user whose data is being tested.
- Deterministic past dates are used for all expense insertions so preset-
  preset logic in the profile route never interferes with assertions.
- No test relies on another test's side effects — all data is self-contained.
"""

import uuid
from datetime import date

import pytest
from werkzeug.security import generate_password_hash

from database.db import get_db, create_user


# ------------------------------------------------------------------ #
# Shared test-data helpers                                            #
# ------------------------------------------------------------------ #

VALID_CATEGORIES = [
    "Food", "Transport", "Bills", "Health",
    "Entertainment", "Shopping", "Other",
]

# A deterministic past date that will never collide with date-filter presets.
PAST_DATE = "2021-06-15"


def _unique_email():
    return f"addexp_{uuid.uuid4().hex[:8]}@test.com"


def _register_and_login(client, email, password="Testpass1!"):
    """Register a fresh user via the route, log them in, return their DB id."""
    client.post(
        "/register",
        data={
            "name": "Expense Tester",
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


def _get_expenses_for_user(user_id):
    """Return all expense rows for a user from the DB."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM expenses WHERE user_id = ?", (user_id,)
    ).fetchall()
    conn.close()
    return rows


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


# ------------------------------------------------------------------ #
# Auth guard                                                          #
# ------------------------------------------------------------------ #

class TestAddExpenseAuthGuard:
    """
    Both GET and POST /expenses/add must redirect unauthenticated users
    to /login (302).
    """

    def test_get_unauthenticated_redirects_to_login(self, client):
        response = client.get("/expenses/add")
        assert response.status_code == 302, (
            "GET /expenses/add without login must return 302"
        )
        assert "/login" in response.headers["Location"], (
            "Redirect target must be /login"
        )

    def test_post_unauthenticated_redirects_to_login(self, client):
        response = client.post(
            "/expenses/add",
            data={
                "amount": "50.00",
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert response.status_code == 302, (
            "POST /expenses/add without login must return 302"
        )
        assert "/login" in response.headers["Location"], (
            "Redirect target must be /login"
        )

    def test_get_unauthenticated_does_not_render_form(self, client):
        response = client.get("/expenses/add", follow_redirects=True)
        # After following redirect, we should land on the login page
        assert b"login" in response.data.lower() or b"Login" in response.data, (
            "Unauthenticated GET /expenses/add should land on login page"
        )


# ------------------------------------------------------------------ #
# GET /expenses/add — happy path                                      #
# ------------------------------------------------------------------ #

class TestGetAddExpense:
    """
    GET /expenses/add for an authenticated user must render the
    add-expense form with all required elements.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    def test_get_returns_200(self, client):
        self.user_id = _register_and_login(client, self.email)
        response = client.get("/expenses/add")
        assert response.status_code == 200, (
            "GET /expenses/add must return 200 for an authenticated user"
        )

    def test_get_no_longer_returns_stub_string(self, client):
        """Route must render a template, not return the old stub string."""
        self.user_id = _register_and_login(client, self.email)
        response = client.get("/expenses/add")
        assert b"coming in Step" not in response.data, (
            "The stub string must be replaced with a real template"
        )

    def test_get_renders_form_element(self, client):
        self.user_id = _register_and_login(client, self.email)
        response = client.get("/expenses/add")
        assert b"<form" in response.data, (
            "Page must contain a <form> element"
        )

    def test_get_form_has_amount_field(self, client):
        self.user_id = _register_and_login(client, self.email)
        response = client.get("/expenses/add")
        assert b'name="amount"' in response.data, (
            "Form must have an amount input field"
        )

    def test_get_form_has_category_field(self, client):
        self.user_id = _register_and_login(client, self.email)
        response = client.get("/expenses/add")
        assert b'name="category"' in response.data, (
            "Form must have a category select field"
        )

    def test_get_form_has_date_field(self, client):
        self.user_id = _register_and_login(client, self.email)
        response = client.get("/expenses/add")
        assert b'name="date"' in response.data, (
            "Form must have a date input field"
        )

    def test_get_form_has_description_field(self, client):
        self.user_id = _register_and_login(client, self.email)
        response = client.get("/expenses/add")
        assert b'name="description"' in response.data, (
            "Form must have a description input field"
        )

    def test_get_date_prefilled_with_today(self, client):
        """The date field must default to today's date in ISO format."""
        self.user_id = _register_and_login(client, self.email)
        response = client.get("/expenses/add")
        today_iso = date.today().isoformat()
        assert today_iso.encode() in response.data, (
            f"Today's date ({today_iso}) must be pre-filled in the date field"
        )

    def test_get_contains_all_valid_categories(self, client):
        """All 7 valid categories must appear as options in the form."""
        self.user_id = _register_and_login(client, self.email)
        response = client.get("/expenses/add")
        for category in VALID_CATEGORIES:
            assert category.encode() in response.data, (
                f"Category '{category}' must appear as an option in the form"
            )

    def test_get_shows_rupee_symbol(self, client):
        """The add-expense form must display the ₹ symbol."""
        self.user_id = _register_and_login(client, self.email)
        response = client.get("/expenses/add")
        assert "₹".encode() in response.data, (
            "The add-expense page must contain the ₹ symbol"
        )

    def test_get_extends_base_template(self, client):
        """Page must use base.html layout — check for a known base landmark."""
        self.user_id = _register_and_login(client, self.email)
        response = client.get("/expenses/add")
        # base.html includes the app name in the nav/header
        assert b"Spendly" in response.data, (
            "Page must extend base.html (Spendly nav expected)"
        )

    def test_get_has_no_error_message_on_first_load(self, client):
        """Fresh GET must not show any error message."""
        self.user_id = _register_and_login(client, self.email)
        response = client.get("/expenses/add")
        assert b"must be a positive number" not in response.data
        assert b"valid category" not in response.data
        assert b"valid date" not in response.data


# ------------------------------------------------------------------ #
# POST /expenses/add — happy paths                                    #
# ------------------------------------------------------------------ #

class TestPostAddExpenseHappyPath:
    """
    A valid POST must insert the expense into the DB and redirect to /profile.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    def test_valid_post_redirects_to_profile(self, client):
        self.user_id = _register_and_login(client, self.email)
        response = client.post(
            "/expenses/add",
            data={
                "amount": "75.50",
                "category": "Food",
                "date": PAST_DATE,
                "description": "Grocery run",
            },
        )
        assert response.status_code == 302, (
            "Successful POST must return 302 redirect"
        )
        assert "/profile" in response.headers["Location"], (
            "Redirect target must be /profile"
        )

    def test_valid_post_inserts_row_in_db(self, client):
        """DB side effect: the expense row must exist after a successful POST."""
        self.user_id = _register_and_login(client, self.email)
        client.post(
            "/expenses/add",
            data={
                "amount": "120.00",
                "category": "Bills",
                "date": PAST_DATE,
                "description": "Water bill",
            },
        )
        expenses = _get_expenses_for_user(self.user_id)
        assert len(expenses) >= 1, "At least one expense row must exist after POST"
        amounts = [e["amount"] for e in expenses]
        assert 120.00 in amounts, "Inserted amount must be 120.00"

    def test_valid_post_stores_correct_category(self, client):
        self.user_id = _register_and_login(client, self.email)
        client.post(
            "/expenses/add",
            data={
                "amount": "30.00",
                "category": "Transport",
                "date": PAST_DATE,
                "description": "Bus fare",
            },
        )
        expenses = _get_expenses_for_user(self.user_id)
        categories = [e["category"] for e in expenses]
        assert "Transport" in categories, "Category must be stored as 'Transport'"

    def test_valid_post_stores_correct_date(self, client):
        self.user_id = _register_and_login(client, self.email)
        client.post(
            "/expenses/add",
            data={
                "amount": "25.00",
                "category": "Health",
                "date": PAST_DATE,
                "description": "Vitamins",
            },
        )
        expenses = _get_expenses_for_user(self.user_id)
        dates = [e["date"] for e in expenses]
        assert PAST_DATE in dates, f"Date must be stored as '{PAST_DATE}'"

    def test_valid_post_stores_correct_description(self, client):
        self.user_id = _register_and_login(client, self.email)
        client.post(
            "/expenses/add",
            data={
                "amount": "15.00",
                "category": "Entertainment",
                "date": PAST_DATE,
                "description": "Netflix subscription",
            },
        )
        expenses = _get_expenses_for_user(self.user_id)
        descriptions = [e["description"] for e in expenses]
        assert "Netflix subscription" in descriptions, (
            "Description must be stored correctly"
        )

    def test_valid_post_description_optional_succeeds(self, client):
        """Submitting without a description must succeed and redirect."""
        self.user_id = _register_and_login(client, self.email)
        response = client.post(
            "/expenses/add",
            data={
                "amount": "50.00",
                "category": "Shopping",
                "date": PAST_DATE,
                "description": "",
            },
        )
        assert response.status_code == 302, (
            "POST without description must still return 302 redirect"
        )
        assert "/profile" in response.headers["Location"], (
            "Redirect must go to /profile when description is omitted"
        )

    def test_valid_post_without_description_inserts_row(self, client):
        """DB side effect: row must be inserted even with no description."""
        self.user_id = _register_and_login(client, self.email)
        client.post(
            "/expenses/add",
            data={
                "amount": "42.00",
                "category": "Other",
                "date": PAST_DATE,
                "description": "",
            },
        )
        expenses = _get_expenses_for_user(self.user_id)
        assert len(expenses) >= 1, "Row must be inserted even with no description"

    def test_valid_post_description_none_stored_as_null(self, client):
        """When description is omitted, the DB row must store NULL (not empty string)."""
        self.user_id = _register_and_login(client, self.email)
        client.post(
            "/expenses/add",
            data={
                "amount": "10.00",
                "category": "Food",
                "date": PAST_DATE,
                # description intentionally omitted from form data
            },
        )
        expenses = _get_expenses_for_user(self.user_id)
        assert len(expenses) >= 1
        # The most recent row for this user should have NULL description
        descriptions = [e["description"] for e in expenses]
        assert None in descriptions or "" in descriptions, (
            "Description must be stored as NULL when not provided"
        )

    def test_valid_post_expense_appears_on_profile(self, client):
        """After redirect to /profile, the new expense must be visible."""
        self.user_id = _register_and_login(client, self.email)
        client.post(
            "/expenses/add",
            data={
                "amount": "88.00",
                "category": "Food",
                "date": PAST_DATE,
                "description": "Unique desc xy9z7",
            },
            follow_redirects=False,
        )
        profile_response = client.get("/profile")
        assert b"Unique desc xy9z7" in profile_response.data, (
            "Newly added expense must appear in the /profile transactions list"
        )

    @pytest.mark.parametrize("category", VALID_CATEGORIES)
    def test_each_valid_category_is_accepted(self, client, category):
        """Every category in the fixed list must be accepted without error."""
        email = _unique_email()
        user_id = _register_and_login(client, email)
        try:
            response = client.post(
                "/expenses/add",
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
# POST /expenses/add — amount validation                              #
# ------------------------------------------------------------------ #

class TestAddExpenseAmountValidation:
    """
    Invalid or non-positive amounts must re-render the form (200) with
    the error message "Amount must be a positive number." and must NOT
    insert any row.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    @pytest.mark.parametrize("bad_amount", [
        "abc",        # non-numeric string
        "zero",       # word, not a number
        "",           # empty string
        "   ",        # whitespace only
        "1e999",      # overflow-style float string
        "--5",        # double negative
    ])
    def test_non_numeric_amount_rerender(self, client, bad_amount):
        self.user_id = _register_and_login(client, self.email)
        response = client.post(
            "/expenses/add",
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
    def test_non_numeric_amount_no_db_insert(self, client, bad_amount):
        self.user_id = _register_and_login(client, self.email)
        client.post(
            "/expenses/add",
            data={
                "amount": bad_amount,
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        expenses = _get_expenses_for_user(self.user_id)
        assert len(expenses) == 0, (
            f"No expense row must be inserted for amount='{bad_amount}'"
        )

    def test_zero_amount_rerenders_with_error(self, client):
        self.user_id = _register_and_login(client, self.email)
        response = client.post(
            "/expenses/add",
            data={
                "amount": "0",
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert response.status_code == 200, (
            "Zero amount must re-render the form"
        )
        assert b"Amount must be a positive number" in response.data, (
            "Error message must appear for amount=0"
        )

    def test_zero_amount_no_db_insert(self, client):
        self.user_id = _register_and_login(client, self.email)
        client.post(
            "/expenses/add",
            data={
                "amount": "0",
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert len(_get_expenses_for_user(self.user_id)) == 0, (
            "Zero amount must not insert a row"
        )

    def test_zero_decimal_amount_rerenders_with_error(self, client):
        self.user_id = _register_and_login(client, self.email)
        response = client.post(
            "/expenses/add",
            data={
                "amount": "0.00",
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert response.status_code == 200
        assert b"Amount must be a positive number" in response.data

    def test_negative_amount_rerenders_with_error(self, client):
        self.user_id = _register_and_login(client, self.email)
        response = client.post(
            "/expenses/add",
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

    def test_negative_amount_no_db_insert(self, client):
        self.user_id = _register_and_login(client, self.email)
        client.post(
            "/expenses/add",
            data={
                "amount": "-99.99",
                "category": "Food",
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert len(_get_expenses_for_user(self.user_id)) == 0, (
            "Negative amount must not insert a row"
        )

    def test_invalid_amount_form_still_has_category_options(self, client):
        """On error re-render, the category dropdown must still be populated."""
        self.user_id = _register_and_login(client, self.email)
        response = client.post(
            "/expenses/add",
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
# POST /expenses/add — category validation                            #
# ------------------------------------------------------------------ #

class TestAddExpenseCategoryValidation:
    """
    Invalid or missing categories must re-render the form (200) with
    an error message and must NOT insert any row.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    @pytest.mark.parametrize("bad_category", [
        "",                   # empty string
        "Groceries",          # not in the fixed list
        "food",               # wrong case
        "FOOD",               # wrong case
        "Food ",              # trailing space
        " Food",              # leading space
        "InvalidCategory",    # completely arbitrary
        "<script>alert(1)</script>",  # XSS attempt
    ])
    def test_invalid_category_rerenders_form(self, client, bad_category):
        self.user_id = _register_and_login(client, self.email)
        response = client.post(
            "/expenses/add",
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
        response = client.post(
            "/expenses/add",
            data={
                "amount": "50.00",
                "category": bad_category,
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert b"valid category" in response.data.lower() or b"Please select" in response.data, (
            f"Error message must appear for invalid category '{bad_category}'"
        )

    @pytest.mark.parametrize("bad_category", [
        "",
        "Groceries",
        "food",
    ])
    def test_invalid_category_no_db_insert(self, client, bad_category):
        self.user_id = _register_and_login(client, self.email)
        client.post(
            "/expenses/add",
            data={
                "amount": "50.00",
                "category": bad_category,
                "date": PAST_DATE,
                "description": "test",
            },
        )
        assert len(_get_expenses_for_user(self.user_id)) == 0, (
            f"No row must be inserted for invalid category '{bad_category}'"
        )


# ------------------------------------------------------------------ #
# POST /expenses/add — date validation                                #
# ------------------------------------------------------------------ #

class TestAddExpenseDateValidation:
    """
    Malformed or missing date strings must re-render the form (200) with
    the error "Please enter a valid date." and must NOT insert any row.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    @pytest.mark.parametrize("bad_date", [
        "",                     # empty string
        "not-a-date",           # arbitrary string
        "15-06-2021",           # DD-MM-YYYY — wrong format
        "06/15/2021",           # MM/DD/YYYY — wrong format
        "20210615",             # YYYYMMDD — missing hyphens
        "2021-13-01",           # invalid month 13
        "2021-06-32",           # invalid day 32
        "2021-02-30",           # Feb 30 — doesn't exist
        "2021-6-15",            # single-digit month (not zero-padded)
        "2021-06-1",            # single-digit day (not zero-padded)
        "2021-06-15T00:00:00",  # datetime instead of date
        "tomorrow",             # plain English
    ])
    def test_malformed_date_rerenders_form(self, client, bad_date):
        self.user_id = _register_and_login(client, self.email)
        response = client.post(
            "/expenses/add",
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
        response = client.post(
            "/expenses/add",
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
    def test_malformed_date_no_db_insert(self, client, bad_date):
        self.user_id = _register_and_login(client, self.email)
        client.post(
            "/expenses/add",
            data={
                "amount": "50.00",
                "category": "Food",
                "date": bad_date,
                "description": "test",
            },
        )
        assert len(_get_expenses_for_user(self.user_id)) == 0, (
            f"No row must be inserted for malformed date '{bad_date}'"
        )


# ------------------------------------------------------------------ #
# POST — error re-render preserves form data                          #
# ------------------------------------------------------------------ #

class TestAddExpenseErrorRerender:
    """
    When validation fails, the form must be re-rendered (not redirected).
    The response must contain the error message and the form fields so
    the user can correct their input.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    def test_amount_error_preserves_form_structure(self, client):
        """On amount error, the form must still be present in the response."""
        self.user_id = _register_and_login(client, self.email)
        response = client.post(
            "/expenses/add",
            data={
                "amount": "bad",
                "category": "Food",
                "date": PAST_DATE,
                "description": "preserved desc",
            },
        )
        assert b"<form" in response.data, (
            "Form element must still be present on error re-render"
        )

    def test_category_error_re_renders_not_redirects(self, client):
        """Category error must return 200, not a 3xx redirect."""
        self.user_id = _register_and_login(client, self.email)
        response = client.post(
            "/expenses/add",
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

    def test_date_error_re_renders_not_redirects(self, client):
        """Date error must return 200, not a 3xx redirect."""
        self.user_id = _register_and_login(client, self.email)
        response = client.post(
            "/expenses/add",
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

    def test_error_rerender_still_shows_rupee_symbol(self, client):
        """The ₹ symbol must appear even on error re-renders."""
        self.user_id = _register_and_login(client, self.email)
        response = client.post(
            "/expenses/add",
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


# ------------------------------------------------------------------ #
# Edge cases                                                          #
# ------------------------------------------------------------------ #

class TestAddExpenseEdgeCases:
    """
    Edge cases: very small positive amounts, large amounts, SQL injection
    in description, very long description, and special characters.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    def test_minimal_positive_amount_accepted(self, client):
        """0.01 — the smallest valid positive amount — must be accepted."""
        self.user_id = _register_and_login(client, self.email)
        response = client.post(
            "/expenses/add",
            data={
                "amount": "0.01",
                "category": "Food",
                "date": PAST_DATE,
                "description": "minimum amount",
            },
        )
        assert response.status_code == 302, (
            "Amount 0.01 must be accepted and redirect to /profile"
        )
        expenses = _get_expenses_for_user(self.user_id)
        assert any(abs(e["amount"] - 0.01) < 0.001 for e in expenses), (
            "0.01 must be stored in the DB"
        )

    def test_large_amount_accepted(self, client):
        """A large but valid amount must be stored correctly."""
        self.user_id = _register_and_login(client, self.email)
        response = client.post(
            "/expenses/add",
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
        A description containing SQL injection characters must be inserted
        safely (parameterized queries protect against this).
        The row must exist with the literal injection string as description.
        """
        self.user_id = _register_and_login(client, self.email)
        injection = "'); DROP TABLE expenses; --"
        response = client.post(
            "/expenses/add",
            data={
                "amount": "5.00",
                "category": "Other",
                "date": PAST_DATE,
                "description": injection,
            },
        )
        # Must not crash — parameterized queries treat this as a literal string
        assert response.status_code == 302, (
            "SQL injection in description must be handled safely"
        )
        # The expenses table must still exist and contain the row
        expenses = _get_expenses_for_user(self.user_id)
        assert len(expenses) >= 1, "Expenses table must still exist after injection attempt"

    def test_very_long_description_accepted(self, client):
        """A description of 500 characters must not cause an error."""
        self.user_id = _register_and_login(client, self.email)
        long_desc = "x" * 500
        response = client.post(
            "/expenses/add",
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

    def test_amount_with_many_decimal_places_accepted(self, client):
        """
        An amount with many decimal places (e.g. 10.123456) must be
        accepted — it converts to float and is positive.
        """
        self.user_id = _register_and_login(client, self.email)
        response = client.post(
            "/expenses/add",
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

    def test_whitespace_description_treated_as_empty(self, client):
        """
        A description consisting only of whitespace must be treated as
        absent (no row rejection — description is optional).
        """
        self.user_id = _register_and_login(client, self.email)
        response = client.post(
            "/expenses/add",
            data={
                "amount": "20.00",
                "category": "Food",
                "date": PAST_DATE,
                "description": "   ",
            },
        )
        # Whitespace-only description: feature should still succeed
        assert response.status_code == 302, (
            "Whitespace-only description must not block the submission"
        )

    def test_multiple_expenses_same_user_all_inserted(self, client):
        """Multiple sequential POSTs must each insert a separate row."""
        self.user_id = _register_and_login(client, self.email)
        for i in range(3):
            client.post(
                "/expenses/add",
                data={
                    "amount": f"{10 + i}.00",
                    "category": "Food",
                    "date": PAST_DATE,
                    "description": f"expense {i}",
                },
            )
        expenses = _get_expenses_for_user(self.user_id)
        assert len(expenses) == 3, (
            "Each valid POST must create a separate row; expected 3 rows"
        )

"""
Tests for Step 6 — Date-range filter on GET /profile.

Spec: .claude/specs/06-date-filter-profile-page.md

Design notes
------------
- The real get_db() always connects to the file-based spendly.db (DB_PATH in
  database/db.py) regardless of Flask config. We therefore cannot use an
  in-memory SQLite database for query-helper tests.
- Each test class that needs its own expense data creates a fresh user via
  create_user() and inserts expenses with deterministic, well-separated dates.
  All inserted rows are deleted in teardown so they never bleed into other tests.
- Route tests (TestProfileRouteDateFilter) log in as a per-class isolated user
  so their data does not interfere with the seeded demo account.
- The existing conftest.py session-scoped `app` fixture is reused; the `client`
  fixture from conftest.py is also reused.
"""

import uuid
from calendar import monthrange
from datetime import date, timedelta

import pytest
from werkzeug.security import generate_password_hash

from database.db import get_db, create_user
from database.queries import (
    get_summary_stats,
    get_recent_transactions,
    get_category_breakdown,
)


# ------------------------------------------------------------------ #
# Shared test-data helpers                                            #
# ------------------------------------------------------------------ #

def _unique_email():
    return f"filter_test_{uuid.uuid4().hex[:8]}@test.com"


def _make_user():
    """Create a fresh user with no expenses and return their id."""
    return create_user(
        "Filter Tester",
        _unique_email(),
        generate_password_hash("Testpass1!"),
    )


def _insert_expenses(user_id, rows):
    """
    Insert expense rows for user_id.

    rows: list of (amount, category, date_str, description) tuples.
    Returns the list of inserted rowids so they can be cleaned up.
    """
    conn = get_db()
    ids = []
    for amount, category, date_str, description in rows:
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, date_str, description),
        )
        ids.append(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.commit()
    conn.close()
    return ids


def _delete_expenses(ids):
    if not ids:
        return
    conn = get_db()
    for eid in ids:
        conn.execute("DELETE FROM expenses WHERE id = ?", (eid,))
    conn.commit()
    conn.close()


def _delete_user(user_id):
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


def _register_and_login(client, email, password="Testpass1!"):
    """
    Register a user via the route, log them in, and return their DB user_id.

    This is the canonical way to create a test user for route tests — it
    ensures the logged-in session matches the user whose expenses are inserted.
    """
    client.post(
        "/register",
        data={
            "name": "Filter Tester",
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
    # Retrieve the user_id so callers can insert expenses under this user
    conn = get_db()
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return row["id"] if row else None


# Fixed deterministic dates for test data
# Using 2020 to guarantee they are in the past and clearly separated.
DATE_JAN = "2020-01-15"   # January 2020
DATE_FEB = "2020-02-10"   # February 2020
DATE_MAR = "2020-03-20"   # March 2020
DATE_APR = "2020-04-05"   # April 2020

# Range that captures only JAN and FEB entries
RANGE_JAN_FEB_FROM = "2020-01-01"
RANGE_JAN_FEB_TO   = "2020-02-28"

# Range that captures only MAR and APR entries
RANGE_MAR_APR_FROM = "2020-03-01"
RANGE_MAR_APR_TO   = "2020-04-30"

# Range with no expenses at all
EMPTY_RANGE_FROM = "2019-01-01"
EMPTY_RANGE_TO   = "2019-12-31"


# ------------------------------------------------------------------ #
# Auth guard (regression)                                             #
# ------------------------------------------------------------------ #

class TestProfileAuthGuard:
    """Unauthenticated access to /profile must always redirect to /login."""

    def test_unauthenticated_no_params_redirects_to_login(self, client):
        response = client.get("/profile")
        assert response.status_code == 302, (
            "Expected 302 redirect for unauthenticated /profile"
        )
        assert "/login" in response.headers["Location"], (
            "Redirect target should be /login"
        )

    def test_unauthenticated_with_date_params_redirects_to_login(self, client):
        response = client.get("/profile?date_from=2020-01-01&date_to=2020-03-31")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_unauthenticated_with_malformed_date_redirects_to_login(self, client):
        response = client.get("/profile?date_from=not-a-date")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]


# ------------------------------------------------------------------ #
# Unfiltered /profile regression                                      #
# ------------------------------------------------------------------ #

class TestProfileUnfiltered:
    """
    GET /profile with no query params must behave identically to Step 5 —
    show all expenses, rupee symbol, correct totals.
    """

    def setup_method(self):
        self.email = _unique_email()

    def test_unfiltered_returns_200(self, client):
        _register_and_login(client, self.email)
        response = client.get("/profile")
        assert response.status_code == 200, "Unfiltered /profile must return 200"

    def test_unfiltered_contains_rupee_symbol(self, client):
        _register_and_login(client, self.email)
        response = client.get("/profile")
        assert "₹".encode() in response.data, (
            "Profile page must contain the ₹ symbol regardless of filter state"
        )

    def test_unfiltered_page_loads_without_flash_error(self, client):
        _register_and_login(client, self.email)
        response = client.get("/profile")
        assert b"Start date must be before end date" not in response.data


# ------------------------------------------------------------------ #
# Route — custom valid date range                                     #
# ------------------------------------------------------------------ #

class TestProfileRouteValidDateRange:
    """
    GET /profile?date_from=X&date_to=Y with X <= Y must:
    - return 200
    - show only expenses within [X, Y] in all three data sections
    - display the ₹ symbol
    - not show a flash error
    """

    def setup_method(self):
        self.email = _unique_email()
        self.expense_ids = []
        # user_id is populated in each test via _register_and_login
        self.user_id = None

    def teardown_method(self):
        _delete_expenses(self.expense_ids)
        if self.user_id:
            _delete_user(self.user_id)

    def _setup_with_client(self, client):
        """Register+login via route to get user_id, then insert test expenses."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_ids = _insert_expenses(
            self.user_id,
            [
                (100.00, "Food",      DATE_JAN, "January food"),
                (200.00, "Bills",     DATE_FEB, "February bills"),
                (300.00, "Transport", DATE_MAR, "March transport"),
                (400.00, "Health",    DATE_APR, "April health"),
            ],
        )

    def test_valid_range_returns_200(self, client):
        self._setup_with_client(client)
        response = client.get(
            f"/profile?date_from={RANGE_JAN_FEB_FROM}&date_to={RANGE_JAN_FEB_TO}"
        )
        assert response.status_code == 200

    def test_valid_range_shows_rupee_symbol(self, client):
        self._setup_with_client(client)
        response = client.get(
            f"/profile?date_from={RANGE_JAN_FEB_FROM}&date_to={RANGE_JAN_FEB_TO}"
        )
        assert "₹".encode() in response.data, (
            "₹ symbol must appear even when a date filter is active"
        )

    def test_valid_range_does_not_show_flash_error(self, client):
        self._setup_with_client(client)
        response = client.get(
            f"/profile?date_from={RANGE_JAN_FEB_FROM}&date_to={RANGE_JAN_FEB_TO}"
        )
        assert b"Start date must be before end date" not in response.data

    def test_valid_range_excludes_out_of_range_expenses(self, client):
        """Expenses in March/April must NOT appear when filtering Jan–Feb."""
        self._setup_with_client(client)
        response = client.get(
            f"/profile?date_from={RANGE_JAN_FEB_FROM}&date_to={RANGE_JAN_FEB_TO}"
        )
        # March transport and April health are outside the range
        assert b"March transport" not in response.data
        assert b"April health" not in response.data

    def test_valid_range_includes_in_range_expenses(self, client):
        """Expenses in January and February must appear when filtering Jan–Feb."""
        self._setup_with_client(client)
        response = client.get(
            f"/profile?date_from={RANGE_JAN_FEB_FROM}&date_to={RANGE_JAN_FEB_TO}"
        )
        assert b"January food" in response.data
        assert b"February bills" in response.data

    def test_valid_range_shows_correct_total(self, client):
        """Summary total must reflect only the filtered expenses (100 + 200 = 300)."""
        self._setup_with_client(client)
        response = client.get(
            f"/profile?date_from={RANGE_JAN_FEB_FROM}&date_to={RANGE_JAN_FEB_TO}"
        )
        assert b"300" in response.data, (
            "Expected total of ₹300.00 for Jan–Feb filter"
        )


# ------------------------------------------------------------------ #
# Route — reversed date range                                         #
# ------------------------------------------------------------------ #

class TestProfileRouteReversedDateRange:
    """
    GET /profile?date_from=X&date_to=Y with X > Y must:
    - return 200 (not a 4xx error)
    - flash the message "Start date must be before end date."
    - fall back to the unfiltered view (all expenses visible)
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None
        self.expense_ids = []

    def teardown_method(self):
        _delete_expenses(self.expense_ids)
        if self.user_id:
            _delete_user(self.user_id)

    def _setup_with_client(self, client):
        self.user_id = _register_and_login(client, self.email)
        self.expense_ids = _insert_expenses(
            self.user_id,
            [
                (150.00, "Food",  DATE_JAN, "Jan food"),
                (250.00, "Bills", DATE_MAR, "Mar bills"),
            ],
        )

    def test_reversed_range_returns_200(self, client):
        self._setup_with_client(client)
        response = client.get(
            "/profile?date_from=2020-12-31&date_to=2020-01-01",
            follow_redirects=True,
        )
        assert response.status_code == 200, (
            "Reversed date range must return 200, not a 4xx error"
        )

    def test_reversed_range_shows_flash_error(self, client):
        self._setup_with_client(client)
        response = client.get(
            "/profile?date_from=2020-12-31&date_to=2020-01-01",
            follow_redirects=True,
        )
        assert b"Start date must be before end date" in response.data, (
            "Flash message 'Start date must be before end date.' must appear"
        )

    def test_reversed_range_falls_back_to_unfiltered(self, client):
        """After a reversed range, both expenses must be visible (unfiltered)."""
        self._setup_with_client(client)
        response = client.get(
            "/profile?date_from=2020-12-31&date_to=2020-01-01",
            follow_redirects=True,
        )
        assert b"Jan food" in response.data, (
            "Jan food must appear in unfiltered fallback"
        )
        assert b"Mar bills" in response.data, (
            "Mar bills must appear in unfiltered fallback"
        )

    def test_reversed_range_rupee_still_present(self, client):
        self._setup_with_client(client)
        response = client.get(
            "/profile?date_from=2020-12-31&date_to=2020-01-01",
            follow_redirects=True,
        )
        assert "₹".encode() in response.data


# ------------------------------------------------------------------ #
# Route — malformed date strings                                      #
# ------------------------------------------------------------------ #

class TestProfileRouteMalformedDates:
    """
    Malformed date strings must not crash the app.
    The route must silently fall back to unfiltered view.
    """

    def setup_method(self):
        self.email = _unique_email()

    @pytest.mark.parametrize("query_string", [
        "date_from=not-a-date",
        "date_to=not-a-date",
        "date_from=not-a-date&date_to=also-bad",
        "date_from=2020-99-99",          # invalid month/day
        "date_from=20200101",            # missing hyphens
        "date_from=01-15-2020",          # wrong format (MM-DD-YYYY)
        "date_from=2020-01-01T00:00:00", # datetime instead of date
        "date_from=",                    # empty string
    ])
    def test_malformed_date_returns_200(self, client, query_string):
        _register_and_login(client, self.email)
        response = client.get(f"/profile?{query_string}")
        assert response.status_code == 200, (
            f"Malformed date '{query_string}' must not crash the app — expected 200"
        )

    @pytest.mark.parametrize("query_string", [
        "date_from=not-a-date",
        "date_to=not-a-date",
        "date_from=not-a-date&date_to=also-bad",
    ])
    def test_malformed_date_does_not_show_date_error_flash(self, client, query_string):
        """Malformed dates fall back silently — no flash error message."""
        _register_and_login(client, self.email)
        response = client.get(f"/profile?{query_string}")
        assert b"Start date must be before end date" not in response.data


# ------------------------------------------------------------------ #
# Route — empty result range                                          #
# ------------------------------------------------------------------ #

class TestProfileRouteEmptyResultRange:
    """
    When the valid date range contains no matching expenses the page must:
    - return 200
    - show ₹0.00 total spent
    - show 0 transactions
    - show no category rows / empty breakdown
    - not raise any error
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None
        self.expense_ids = []

    def teardown_method(self):
        _delete_expenses(self.expense_ids)
        if self.user_id:
            _delete_user(self.user_id)

    def _setup_with_client(self, client):
        # Insert expenses only in 2020; query with a 2019 range → zero matches
        self.user_id = _register_and_login(client, self.email)
        self.expense_ids = _insert_expenses(
            self.user_id,
            [(500.00, "Food", DATE_JAN, "Should not appear")],
        )

    def test_empty_range_returns_200(self, client):
        self._setup_with_client(client)
        response = client.get(
            f"/profile?date_from={EMPTY_RANGE_FROM}&date_to={EMPTY_RANGE_TO}"
        )
        assert response.status_code == 200

    def test_empty_range_shows_zero_total(self, client):
        self._setup_with_client(client)
        response = client.get(
            f"/profile?date_from={EMPTY_RANGE_FROM}&date_to={EMPTY_RANGE_TO}"
        )
        assert b"0.00" in response.data, (
            "Zero-expense range must display 0.00 total"
        )

    def test_empty_range_rupee_symbol_still_present(self, client):
        self._setup_with_client(client)
        response = client.get(
            f"/profile?date_from={EMPTY_RANGE_FROM}&date_to={EMPTY_RANGE_TO}"
        )
        assert "₹".encode() in response.data, (
            "₹ symbol must appear even when no expenses match the filter"
        )

    def test_empty_range_does_not_show_expense_outside_range(self, client):
        self._setup_with_client(client)
        response = client.get(
            f"/profile?date_from={EMPTY_RANGE_FROM}&date_to={EMPTY_RANGE_TO}"
        )
        assert b"Should not appear" not in response.data


# ------------------------------------------------------------------ #
# Query helper — get_summary_stats date filtering                     #
# ------------------------------------------------------------------ #

class TestGetSummaryStatsDateFilter:
    """
    get_summary_stats(user_id, date_from=..., date_to=...) must return
    totals that include only expenses within the given range.
    """

    def setup_method(self):
        self.user_id = _make_user()
        self.expense_ids = _insert_expenses(
            self.user_id,
            [
                (100.00, "Food",      DATE_JAN, "Jan"),   # in range
                (200.00, "Bills",     DATE_FEB, "Feb"),   # in range
                (300.00, "Transport", DATE_MAR, "Mar"),   # out of range
                (400.00, "Health",    DATE_APR, "Apr"),   # out of range
            ],
        )

    def teardown_method(self):
        _delete_expenses(self.expense_ids)
        _delete_user(self.user_id)

    def test_date_filter_transaction_count(self):
        result = get_summary_stats(
            self.user_id,
            date_from=RANGE_JAN_FEB_FROM,
            date_to=RANGE_JAN_FEB_TO,
        )
        assert result["transaction_count"] == 2, (
            "Only 2 expenses fall in Jan–Feb range"
        )

    def test_date_filter_total_spent(self):
        result = get_summary_stats(
            self.user_id,
            date_from=RANGE_JAN_FEB_FROM,
            date_to=RANGE_JAN_FEB_TO,
        )
        assert abs(result["total_spent"] - 300.00) < 0.01, (
            "Total for Jan–Feb must be 100 + 200 = 300.00"
        )

    def test_date_filter_top_category(self):
        result = get_summary_stats(
            self.user_id,
            date_from=RANGE_JAN_FEB_FROM,
            date_to=RANGE_JAN_FEB_TO,
        )
        # Bills (200) > Food (100) in Jan–Feb range
        assert result["top_category"] == "Bills"

    def test_only_date_from_filters_lower_bound(self):
        """date_from only: expenses on or after that date are included."""
        result = get_summary_stats(
            self.user_id,
            date_from=RANGE_MAR_APR_FROM,  # 2020-03-01
        )
        # Only March and April match (300 + 400 = 700)
        assert result["transaction_count"] == 2
        assert abs(result["total_spent"] - 700.00) < 0.01

    def test_only_date_to_filters_upper_bound(self):
        """date_to only: expenses on or before that date are included."""
        result = get_summary_stats(
            self.user_id,
            date_to=RANGE_JAN_FEB_TO,  # 2020-02-28
        )
        # Only January and February match (100 + 200 = 300)
        assert result["transaction_count"] == 2
        assert abs(result["total_spent"] - 300.00) < 0.01

    def test_empty_range_returns_zero_total(self):
        result = get_summary_stats(
            self.user_id,
            date_from=EMPTY_RANGE_FROM,
            date_to=EMPTY_RANGE_TO,
        )
        assert result["total_spent"] == 0.0
        assert result["transaction_count"] == 0
        assert result["top_category"] is None

    def test_no_filter_returns_all_expenses(self):
        result = get_summary_stats(self.user_id)
        assert result["transaction_count"] == 4
        assert abs(result["total_spent"] - 1000.00) < 0.01

    def test_inclusive_lower_bound(self):
        """date_from is inclusive — an expense ON date_from must be included."""
        result = get_summary_stats(
            self.user_id,
            date_from=DATE_JAN,
            date_to=DATE_JAN,
        )
        assert result["transaction_count"] == 1
        assert abs(result["total_spent"] - 100.00) < 0.01

    def test_inclusive_upper_bound(self):
        """date_to is inclusive — an expense ON date_to must be included."""
        result = get_summary_stats(
            self.user_id,
            date_from=DATE_APR,
            date_to=DATE_APR,
        )
        assert result["transaction_count"] == 1
        assert abs(result["total_spent"] - 400.00) < 0.01


# ------------------------------------------------------------------ #
# Query helper — get_recent_transactions date filtering               #
# ------------------------------------------------------------------ #

class TestGetRecentTransactionsDateFilter:
    """
    get_recent_transactions(user_id, date_from=..., date_to=...) must return
    only transactions within the range, newest first.
    """

    def setup_method(self):
        self.user_id = _make_user()
        self.expense_ids = _insert_expenses(
            self.user_id,
            [
                (100.00, "Food",      DATE_JAN, "Jan tx"),
                (200.00, "Bills",     DATE_FEB, "Feb tx"),
                (300.00, "Transport", DATE_MAR, "Mar tx"),
                (400.00, "Health",    DATE_APR, "Apr tx"),
            ],
        )

    def teardown_method(self):
        _delete_expenses(self.expense_ids)
        _delete_user(self.user_id)

    def test_date_filter_returns_correct_count(self):
        txs = get_recent_transactions(
            self.user_id,
            date_from=RANGE_JAN_FEB_FROM,
            date_to=RANGE_JAN_FEB_TO,
        )
        assert len(txs) == 2, "Only 2 transactions fall in the Jan–Feb range"

    def test_date_filter_excludes_out_of_range(self):
        txs = get_recent_transactions(
            self.user_id,
            date_from=RANGE_JAN_FEB_FROM,
            date_to=RANGE_JAN_FEB_TO,
        )
        descriptions = {t["description"] for t in txs}
        assert "Mar tx" not in descriptions
        assert "Apr tx" not in descriptions

    def test_date_filter_includes_in_range(self):
        txs = get_recent_transactions(
            self.user_id,
            date_from=RANGE_JAN_FEB_FROM,
            date_to=RANGE_JAN_FEB_TO,
        )
        descriptions = {t["description"] for t in txs}
        assert "Jan tx" in descriptions
        assert "Feb tx" in descriptions

    def test_date_filter_ordering_newest_first(self):
        txs = get_recent_transactions(
            self.user_id,
            date_from=RANGE_JAN_FEB_FROM,
            date_to=RANGE_JAN_FEB_TO,
        )
        dates = [t["date"] for t in txs]
        assert dates == sorted(dates, reverse=True), (
            "Filtered transactions must still be ordered newest first"
        )

    def test_date_filter_empty_range_returns_empty_list(self):
        txs = get_recent_transactions(
            self.user_id,
            date_from=EMPTY_RANGE_FROM,
            date_to=EMPTY_RANGE_TO,
        )
        assert txs == [], "No transactions in range must return an empty list"

    def test_no_filter_returns_all_transactions(self):
        txs = get_recent_transactions(self.user_id)
        assert len(txs) == 4

    def test_limit_still_respected_with_date_filter(self):
        """limit param must still apply when a date filter is active."""
        txs = get_recent_transactions(
            self.user_id,
            limit=1,
            date_from=RANGE_JAN_FEB_FROM,
            date_to=RANGE_JAN_FEB_TO,
        )
        assert len(txs) == 1

    def test_each_row_has_required_keys_with_filter(self):
        txs = get_recent_transactions(
            self.user_id,
            date_from=RANGE_JAN_FEB_FROM,
            date_to=RANGE_JAN_FEB_TO,
        )
        for tx in txs:
            assert {"date", "description", "category", "amount"} <= set(tx.keys())


# ------------------------------------------------------------------ #
# Query helper — get_category_breakdown date filtering                #
# ------------------------------------------------------------------ #

class TestGetCategoryBreakdownDateFilter:
    """
    get_category_breakdown(user_id, date_from=..., date_to=...) must return
    only categories that have expenses in the range; percentages must sum to 100.
    """

    def setup_method(self):
        self.user_id = _make_user()
        self.expense_ids = _insert_expenses(
            self.user_id,
            [
                (100.00, "Food",      DATE_JAN, "Jan food"),
                (200.00, "Bills",     DATE_FEB, "Feb bills"),
                (300.00, "Transport", DATE_MAR, "Mar transport"),
                (400.00, "Health",    DATE_APR, "Apr health"),
            ],
        )

    def teardown_method(self):
        _delete_expenses(self.expense_ids)
        _delete_user(self.user_id)

    def test_date_filter_returns_only_matching_categories(self):
        cats = get_category_breakdown(
            self.user_id,
            date_from=RANGE_JAN_FEB_FROM,
            date_to=RANGE_JAN_FEB_TO,
        )
        names = {c["name"] for c in cats}
        assert names == {"Food", "Bills"}, (
            "Only categories with expenses in Jan–Feb should appear"
        )

    def test_date_filter_pct_sums_to_100(self):
        cats = get_category_breakdown(
            self.user_id,
            date_from=RANGE_JAN_FEB_FROM,
            date_to=RANGE_JAN_FEB_TO,
        )
        assert sum(c["pct"] for c in cats) == 100, (
            "Category percentages must sum to 100 even with date filter active"
        )

    def test_date_filter_ordered_by_amount_desc(self):
        cats = get_category_breakdown(
            self.user_id,
            date_from=RANGE_JAN_FEB_FROM,
            date_to=RANGE_JAN_FEB_TO,
        )
        amounts = [c["amount"] for c in cats]
        assert amounts == sorted(amounts, reverse=True)

    def test_date_filter_highest_category_is_bills(self):
        cats = get_category_breakdown(
            self.user_id,
            date_from=RANGE_JAN_FEB_FROM,
            date_to=RANGE_JAN_FEB_TO,
        )
        assert cats[0]["name"] == "Bills", (
            "Bills (200) should be top category in Jan–Feb range"
        )

    def test_date_filter_empty_range_returns_empty_list(self):
        cats = get_category_breakdown(
            self.user_id,
            date_from=EMPTY_RANGE_FROM,
            date_to=EMPTY_RANGE_TO,
        )
        assert cats == [], (
            "Empty range must return an empty list, not raise an error"
        )

    def test_no_filter_returns_all_categories(self):
        cats = get_category_breakdown(self.user_id)
        names = {c["name"] for c in cats}
        assert names == {"Food", "Bills", "Transport", "Health"}

    def test_date_filter_each_row_has_required_keys(self):
        cats = get_category_breakdown(
            self.user_id,
            date_from=RANGE_JAN_FEB_FROM,
            date_to=RANGE_JAN_FEB_TO,
        )
        for cat in cats:
            assert {"name", "amount", "pct"} <= set(cat.keys())

    def test_date_filter_pct_values_are_integers(self):
        cats = get_category_breakdown(
            self.user_id,
            date_from=RANGE_JAN_FEB_FROM,
            date_to=RANGE_JAN_FEB_TO,
        )
        for cat in cats:
            assert isinstance(cat["pct"], int), (
                "pct values must be integers (not floats)"
            )


# ------------------------------------------------------------------ #
# Active preset detection in template context                         #
# ------------------------------------------------------------------ #

class TestActivePresetDetection:
    """
    The route must pass the correct active_preset value to the template
    so the filter bar can highlight the right button.
    We verify this indirectly via HTML rendered by the template since we
    cannot inspect the template context directly through the test client.
    """

    def setup_method(self):
        self.email = _unique_email()

    def test_no_params_active_preset_all_time(self, client):
        """No query params → 'All Time' preset is active."""
        _register_and_login(client, self.email)
        response = client.get("/profile")
        # The template should render the 'All Time' button as active
        # At minimum, the page must render without error
        assert response.status_code == 200

    def test_this_month_preset_params(self, client):
        """
        date_from=<first of current month>&date_to=<today> should resolve
        to the 'this_month' preset — the page must return 200.
        """
        _register_and_login(client, self.email)
        today = date.today()
        first_of_month = today.replace(day=1).isoformat()
        today_str = today.isoformat()
        response = client.get(
            f"/profile?date_from={first_of_month}&date_to={today_str}"
        )
        assert response.status_code == 200

    def test_custom_range_params_return_200(self, client):
        """An arbitrary valid range that matches no preset → custom, still 200."""
        _register_and_login(client, self.email)
        response = client.get(
            "/profile?date_from=2020-01-01&date_to=2020-06-30"
        )
        assert response.status_code == 200

    def test_all_time_link_on_page(self, client):
        """The profile page must contain a link/button for 'All Time'."""
        _register_and_login(client, self.email)
        response = client.get("/profile")
        assert b"All Time" in response.data, (
            "Profile page must render an 'All Time' filter option"
        )

    def test_this_month_link_on_page(self, client):
        _register_and_login(client, self.email)
        response = client.get("/profile")
        assert b"This Month" in response.data

    def test_last_3_months_link_on_page(self, client):
        _register_and_login(client, self.email)
        response = client.get("/profile")
        assert b"Last 3 Months" in response.data

    def test_last_6_months_link_on_page(self, client):
        _register_and_login(client, self.email)
        response = client.get("/profile")
        assert b"Last 6 Months" in response.data


# ------------------------------------------------------------------ #
# Rupee symbol invariant across all filter states                     #
# ------------------------------------------------------------------ #

class TestRupeeSymbolInvariant:
    """
    The ₹ symbol must appear in all filter states:
    unfiltered, filtered, reversed-range fallback, empty-range, malformed-date.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None
        self.expense_ids = []

    def teardown_method(self):
        _delete_expenses(self.expense_ids)
        if self.user_id:
            _delete_user(self.user_id)

    def _setup_with_client(self, client):
        self.user_id = _register_and_login(client, self.email)
        self.expense_ids = _insert_expenses(
            self.user_id,
            [(50.00, "Food", DATE_JAN, "Rupee test expense")],
        )

    @pytest.mark.parametrize("query_string", [
        "",                                              # unfiltered
        "?date_from=2020-01-01&date_to=2020-01-31",     # filtered — expense in range
        "?date_from=2019-01-01&date_to=2019-12-31",     # empty range
        "?date_from=2020-12-31&date_to=2020-01-01",     # reversed range
        "?date_from=not-a-date",                        # malformed
    ])
    def test_rupee_symbol_present(self, client, query_string):
        self._setup_with_client(client)
        response = client.get(f"/profile{query_string}", follow_redirects=True)
        assert response.status_code == 200
        assert "₹".encode() in response.data, (
            f"₹ symbol missing for query_string='{query_string}'"
        )

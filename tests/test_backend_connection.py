import re
import uuid
import pytest
from database.db import get_db, create_user
from werkzeug.security import generate_password_hash
from database.queries import (
    get_user_by_id,
    get_summary_stats,
    get_recent_transactions,
    get_category_breakdown,
)


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _seed_user_id():
    """Return the id of the seeded demo user."""
    conn = get_db()
    row = conn.execute("SELECT id FROM users WHERE email = ?", ("demo@spendly.com",)).fetchone()
    conn.close()
    return row["id"]


def _create_bare_user():
    """Insert a user with no expenses and return their id."""
    return create_user("Bare User", f"bare_{uuid.uuid4().hex}@test.com",
                       generate_password_hash("testpass"))


def _login(client):
    client.post("/login", data={"email": "demo@spendly.com", "password": "demo123"})


# ------------------------------------------------------------------ #
# get_user_by_id                                                      #
# ------------------------------------------------------------------ #

class TestGetUserById:
    def test_returns_expected_keys(self):
        uid = _seed_user_id()
        result = get_user_by_id(uid)
        assert set(result.keys()) >= {"name", "email", "member_since"}

    def test_name_and_email_correct(self):
        uid = _seed_user_id()
        result = get_user_by_id(uid)
        assert result["name"] == "Demo User"
        assert result["email"] == "demo@spendly.com"

    def test_member_since_format(self):
        uid = _seed_user_id()
        result = get_user_by_id(uid)
        assert re.match(r"^\w+ \d{4}$", result["member_since"])

    def test_nonexistent_user_returns_none(self):
        assert get_user_by_id(99999) is None


# ------------------------------------------------------------------ #
# get_summary_stats                                                   #
# ------------------------------------------------------------------ #

class TestGetSummaryStats:
    def test_returns_expected_keys(self):
        uid = _seed_user_id()
        result = get_summary_stats(uid)
        assert set(result.keys()) >= {"total_spent", "transaction_count", "top_category"}

    def test_transaction_count_is_8(self):
        uid = _seed_user_id()
        assert get_summary_stats(uid)["transaction_count"] == 8

    def test_total_spent(self):
        uid = _seed_user_id()
        assert abs(get_summary_stats(uid)["total_spent"] - 322.49) < 0.01

    def test_top_category_is_bills(self):
        uid = _seed_user_id()
        assert get_summary_stats(uid)["top_category"] == "Bills"

    def test_empty_user_returns_zeros(self):
        uid = _create_bare_user()
        result = get_summary_stats(uid)
        assert result["total_spent"] == 0.0
        assert result["transaction_count"] == 0
        assert result["top_category"] is None


# ------------------------------------------------------------------ #
# get_recent_transactions                                             #
# ------------------------------------------------------------------ #

class TestGetRecentTransactions:
    def test_returns_list(self):
        uid = _seed_user_id()
        assert isinstance(get_recent_transactions(uid), list)

    def test_seed_user_has_8_transactions(self):
        uid = _seed_user_id()
        assert len(get_recent_transactions(uid)) == 8

    def test_each_row_has_expected_keys(self):
        uid = _seed_user_id()
        for tx in get_recent_transactions(uid):
            assert {"date", "description", "category", "amount"} <= set(tx.keys())

    def test_ordered_newest_first(self):
        uid = _seed_user_id()
        txs = get_recent_transactions(uid)
        assert txs[0]["date"] >= txs[-1]["date"]

    def test_custom_limit(self):
        uid = _seed_user_id()
        assert len(get_recent_transactions(uid, limit=3)) == 3

    def test_empty_user_returns_empty_list(self):
        uid = _create_bare_user()
        assert get_recent_transactions(uid) == []


# ------------------------------------------------------------------ #
# get_category_breakdown                                              #
# ------------------------------------------------------------------ #

class TestGetCategoryBreakdown:
    def test_returns_7_categories(self):
        uid = _seed_user_id()
        assert len(get_category_breakdown(uid)) == 7

    def test_each_row_has_expected_keys(self):
        uid = _seed_user_id()
        for cat in get_category_breakdown(uid):
            assert {"name", "amount", "pct"} <= set(cat.keys())

    def test_pct_sums_to_100(self):
        uid = _seed_user_id()
        assert sum(c["pct"] for c in get_category_breakdown(uid)) == 100

    def test_pct_values_are_integers(self):
        uid = _seed_user_id()
        for cat in get_category_breakdown(uid):
            assert isinstance(cat["pct"], int)

    def test_ordered_by_amount_desc(self):
        uid = _seed_user_id()
        cats = get_category_breakdown(uid)
        assert cats[0]["amount"] >= cats[1]["amount"]

    def test_bills_is_first(self):
        uid = _seed_user_id()
        assert get_category_breakdown(uid)[0]["name"] == "Bills"

    def test_empty_user_returns_empty_list(self):
        uid = _create_bare_user()
        assert get_category_breakdown(uid) == []


# ------------------------------------------------------------------ #
# GET /profile route                                                  #
# ------------------------------------------------------------------ #

class TestProfileRoute:
    def test_unauthenticated_redirects(self, client):
        response = client.get("/profile")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_authenticated_returns_200(self, client):
        _login(client)
        response = client.get("/profile")
        assert response.status_code == 200

    def test_contains_user_name(self, client):
        _login(client)
        assert b"Demo User" in client.get("/profile").data

    def test_contains_rupee_symbol(self, client):
        _login(client)
        assert "₹".encode() in client.get("/profile").data

    def test_contains_bills(self, client):
        _login(client)
        assert b"Bills" in client.get("/profile").data

    def test_contains_total_spent(self, client):
        _login(client)
        assert b"322.49" in client.get("/profile").data

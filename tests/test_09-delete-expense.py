"""
Tests for Step 9 — Delete Expense feature.

Spec: .claude/specs/09-delete-expense.md

Design notes
------------
- Reuses the session-scoped `app` and function-scoped `client` fixtures from
  conftest.py.  The real file-based spendly.db is used (same pattern as
  test_07 and test_08), so every test that writes data cleans up via
  teardown_method / finally blocks.
- `_register_and_login` creates a fresh user per test class instance via the
  route, keeping the session cookie bound to that user.
- `_seed_expense` inserts a known expense row directly into the DB so tests
  have a deterministic expense ID without going through the add-expense form.
- `_create_user_direct` inserts a user without starting a session — used to
  set up the "owner" in cross-user 403 tests.
- All teardown deletes expenses before users to respect the FK constraint.
- PAST_DATE is a fixed historical ISO date that never collides with any
  date-filter preset logic in the profile route.
"""

import uuid

import pytest
from werkzeug.security import generate_password_hash

from database.db import get_db, get_expense_by_id


# ------------------------------------------------------------------ #
# Constants                                                           #
# ------------------------------------------------------------------ #

PAST_DATE = "2021-06-15"


# ------------------------------------------------------------------ #
# DB helpers                                                          #
# ------------------------------------------------------------------ #

def _unique_email():
    return f"del_exp_{uuid.uuid4().hex[:8]}@test.com"


def _register_and_login(client, email, password="Testpass1!"):
    """Register a fresh user through the route and log them in.
    Returns the DB id of the created user."""
    client.post(
        "/register",
        data={
            "name": "Delete Tester",
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


def _seed_expense(user_id, amount=50.00, category="Food",
                  expense_date=PAST_DATE, description="Test expense"):
    """Insert one expense row directly into the DB.  Returns the new expense id."""
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


def _expense_exists(expense_id):
    """Return True if an expense row with the given id exists in the DB."""
    row = get_expense_by_id(expense_id)
    return row is not None


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

class TestDeleteExpenseAuthGuard:
    """
    POST /expenses/<id>/delete must redirect unauthenticated users to
    /login (302) without touching the database.
    """

    def setup_method(self):
        # We need a real expense in the DB so the auth check fires before
        # any 404 that could mask a missing auth guard.
        self.owner_email = _unique_email()
        self.owner_id = _create_user_direct("Auth Owner", self.owner_email)
        self.expense_id = _seed_expense(self.owner_id)

    def teardown_method(self):
        if self.owner_id:
            _delete_expenses_for_user(self.owner_id)
            _delete_user(self.owner_id)

    def test_unauthenticated_post_returns_302(self, client):
        response = client.post(f"/expenses/{self.expense_id}/delete")
        assert response.status_code == 302, (
            "POST /expenses/<id>/delete without login must return 302"
        )

    def test_unauthenticated_post_redirects_to_login(self, client):
        response = client.post(f"/expenses/{self.expense_id}/delete")
        assert "/login" in response.headers["Location"], (
            "Unauthenticated POST must redirect to /login"
        )

    def test_unauthenticated_post_follow_redirects_shows_login_page(self, client):
        response = client.post(
            f"/expenses/{self.expense_id}/delete", follow_redirects=True
        )
        assert b"login" in response.data.lower() or b"Login" in response.data, (
            "Following the redirect from an unauthenticated POST must land on the login page"
        )

    def test_unauthenticated_post_does_not_delete_expense(self, client):
        """The expense row must still exist after an unauthenticated request."""
        client.post(f"/expenses/{self.expense_id}/delete")
        assert _expense_exists(self.expense_id), (
            "Expense must not be deleted when the request is unauthenticated"
        )


# ------------------------------------------------------------------ #
# Happy path — authenticated owner                                    #
# ------------------------------------------------------------------ #

class TestDeleteExpenseHappyPath:
    """
    POST /expenses/<id>/delete by the authenticated owner must delete
    the expense and redirect to /profile.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None
        self.expense_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    def test_successful_delete_returns_302(self, client):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(f"/expenses/{self.expense_id}/delete")
        assert response.status_code == 302, (
            "Successful DELETE must return 302"
        )

    def test_successful_delete_redirects_to_profile(self, client):
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(f"/expenses/{self.expense_id}/delete")
        assert "/profile" in response.headers["Location"], (
            "Successful DELETE must redirect to /profile"
        )

    def test_successful_delete_follows_redirect_to_profile(self, client):
        """Following the redirect must land on the profile page."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(
            f"/expenses/{self.expense_id}/delete", follow_redirects=True
        )
        assert response.status_code == 200, (
            "Following the redirect must return 200 on /profile"
        )

    def test_successful_delete_does_not_render_success_template(self, client):
        """The feature spec requires a redirect, not a rendered success page."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        response = client.post(f"/expenses/{self.expense_id}/delete")
        # A redirect must not have a rendered body with a confirmation message
        assert response.status_code == 302, (
            "Delete must redirect (302), not render a success template"
        )


# ------------------------------------------------------------------ #
# DB side effects                                                     #
# ------------------------------------------------------------------ #

class TestDeleteExpenseDbSideEffects:
    """
    After a successful delete, the expense row must no longer exist in
    the database and must not appear on the profile page.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None
        self.expense_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    def test_expense_row_removed_from_db(self, client):
        """DB side effect: the row must be gone after a successful POST."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        assert _expense_exists(self.expense_id), (
            "Pre-condition: expense must exist before delete"
        )
        client.post(f"/expenses/{self.expense_id}/delete")
        assert not _expense_exists(self.expense_id), (
            "Expense row must not exist in the DB after successful delete"
        )

    def test_get_expense_by_id_returns_none_after_delete(self, client):
        """get_expense_by_id must return None for the deleted expense id."""
        self.user_id = _register_and_login(client, self.email)
        self.expense_id = _seed_expense(self.user_id)
        client.post(f"/expenses/{self.expense_id}/delete")
        assert get_expense_by_id(self.expense_id) is None, (
            "get_expense_by_id must return None for a deleted expense"
        )

    def test_deleted_expense_not_visible_on_profile(self, client):
        """After delete, the expense description must not appear on /profile."""
        self.user_id = _register_and_login(client, self.email)
        unique_desc = f"UniqueDeleteDesc_{uuid.uuid4().hex[:6]}"
        self.expense_id = _seed_expense(
            self.user_id, description=unique_desc
        )
        # Confirm it IS visible before delete
        profile_before = client.get("/profile")
        assert unique_desc.encode() in profile_before.data, (
            "Pre-condition: description must appear on /profile before delete"
        )
        # Delete it
        client.post(f"/expenses/{self.expense_id}/delete")
        # Should no longer be visible
        profile_after = client.get("/profile")
        assert unique_desc.encode() not in profile_after.data, (
            "Deleted expense must no longer appear on /profile"
        )

    def test_only_target_expense_is_deleted(self, client):
        """Deleting one expense must not remove other expenses for the same user."""
        self.user_id = _register_and_login(client, self.email)
        expense_to_delete = _seed_expense(
            self.user_id, description="ToDelete", amount=10.00
        )
        expense_to_keep = _seed_expense(
            self.user_id, description="ToKeep", amount=20.00
        )
        client.post(f"/expenses/{expense_to_delete}/delete")
        assert not _expense_exists(expense_to_delete), (
            "Target expense must be deleted"
        )
        assert _expense_exists(expense_to_keep), (
            "Other expense belonging to the same user must not be deleted"
        )
        # Clean up the remaining expense
        conn = get_db()
        conn.execute("DELETE FROM expenses WHERE id = ?", (expense_to_keep,))
        conn.commit()
        conn.close()
        self.expense_id = None  # Prevent teardown from double-deleting


# ------------------------------------------------------------------ #
# 404 — non-existent expense                                          #
# ------------------------------------------------------------------ #

class TestDeleteExpense404:
    """
    POST /expenses/<nonexistent-id>/delete must return 404.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    def test_nonexistent_expense_returns_404(self, client):
        self.user_id = _register_and_login(client, self.email)
        response = client.post("/expenses/999999/delete")
        assert response.status_code == 404, (
            "POST /expenses/<nonexistent-id>/delete must return 404"
        )

    def test_very_large_nonexistent_id_returns_404(self, client):
        """An extremely large id that cannot exist in the DB must return 404."""
        self.user_id = _register_and_login(client, self.email)
        response = client.post("/expenses/2147483647/delete")
        assert response.status_code == 404, (
            "A very large non-existent expense id must return 404"
        )

    def test_delete_already_deleted_expense_returns_404(self, client):
        """Posting delete a second time to the same (now-gone) id must return 404."""
        self.user_id = _register_and_login(client, self.email)
        expense_id = _seed_expense(self.user_id)
        # First delete succeeds
        first = client.post(f"/expenses/{expense_id}/delete")
        assert first.status_code == 302, (
            "First delete must succeed with 302"
        )
        # Second delete — row is gone
        second = client.post(f"/expenses/{expense_id}/delete")
        assert second.status_code == 404, (
            "Deleting an already-deleted expense must return 404"
        )


# ------------------------------------------------------------------ #
# 403 — ownership check                                               #
# ------------------------------------------------------------------ #

class TestDeleteExpenseOwnershipCheck:
    """
    POST /expenses/<id>/delete for an expense owned by a different user
    must return 403.  The expense row must remain unchanged in the DB.
    """

    def setup_method(self):
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
        """Create owner with an expense in DB; log in as the attacker."""
        self.owner_id = _create_user_direct("Owner User", self.owner_email)
        self.expense_id = _seed_expense(
            self.owner_id, description="Owner expense"
        )
        self.attacker_id = _register_and_login(client, self.attacker_email)

    def test_delete_other_users_expense_returns_403(self, client):
        self._setup_two_users(client)
        response = client.post(f"/expenses/{self.expense_id}/delete")
        assert response.status_code == 403, (
            "POST /expenses/<other-user-expense>/delete must return 403"
        )

    def test_delete_other_users_expense_does_not_delete_row(self, client):
        """The expense row must still exist after a blocked 403 delete."""
        self._setup_two_users(client)
        client.post(f"/expenses/{self.expense_id}/delete")
        assert _expense_exists(self.expense_id), (
            "Expense row must still exist in the DB after a 403 delete attempt"
        )

    def test_403_does_not_affect_owner_data(self, client):
        """After a 403 attempt, the owner's expense data must be fully intact."""
        self._setup_two_users(client)
        client.post(f"/expenses/{self.expense_id}/delete")
        row = get_expense_by_id(self.expense_id)
        assert row is not None, (
            "get_expense_by_id must still return the row after a 403 attempt"
        )
        assert row["user_id"] == self.owner_id, (
            "user_id on the expense must remain the owner's id after 403 attempt"
        )
        assert row["description"] == "Owner expense", (
            "Description must be unchanged after 403 delete attempt"
        )


# ------------------------------------------------------------------ #
# HTTP method guard — GET returns 405                                 #
# ------------------------------------------------------------------ #

class TestDeleteExpenseMethodNotAllowed:
    """
    GET /expenses/<id>/delete must return 405 Method Not Allowed.
    The route is declared POST-only, so Flask rejects all other methods.
    """

    def setup_method(self):
        self.owner_email = _unique_email()
        self.owner_id = _create_user_direct("Method Owner", self.owner_email)
        self.expense_id = _seed_expense(self.owner_id)

    def teardown_method(self):
        if self.owner_id:
            _delete_expenses_for_user(self.owner_id)
            _delete_user(self.owner_id)

    def test_get_returns_405(self, client):
        response = client.get(f"/expenses/{self.expense_id}/delete")
        assert response.status_code == 405, (
            "GET /expenses/<id>/delete must return 405 Method Not Allowed"
        )

    def test_get_does_not_delete_expense(self, client):
        """A GET request must not delete the expense row."""
        client.get(f"/expenses/{self.expense_id}/delete")
        assert _expense_exists(self.expense_id), (
            "Expense must not be deleted by a GET request"
        )

    def test_put_returns_405(self, client):
        response = client.put(f"/expenses/{self.expense_id}/delete")
        assert response.status_code == 405, (
            "PUT /expenses/<id>/delete must return 405 Method Not Allowed"
        )

    def test_patch_returns_405(self, client):
        response = client.patch(f"/expenses/{self.expense_id}/delete")
        assert response.status_code == 405, (
            "PATCH /expenses/<id>/delete must return 405 Method Not Allowed"
        )

    def test_delete_http_verb_returns_405(self, client):
        """The HTTP DELETE verb is not the same as the POST-to-delete endpoint."""
        response = client.delete(f"/expenses/{self.expense_id}/delete")
        assert response.status_code == 405, (
            "HTTP DELETE /expenses/<id>/delete must return 405 Method Not Allowed"
        )


# ------------------------------------------------------------------ #
# Route type safety — non-integer expense_id                          #
# ------------------------------------------------------------------ #

class TestDeleteExpenseRouteTypeSafety:
    """
    The route declares `<int:expense_id>`, so Flask must return 404 for
    any path segment that cannot be cast to an integer.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    @pytest.mark.parametrize("bad_id", [
        "abc",
        "1.5",
        "null",
        "undefined",
        "'; DROP TABLE expenses; --",
    ])
    def test_non_integer_expense_id_returns_404(self, client, bad_id):
        """Flask's <int:> converter must block non-integer segments with 404."""
        self.user_id = _register_and_login(client, self.email)
        response = client.post(f"/expenses/{bad_id}/delete")
        assert response.status_code == 404, (
            f"Non-integer expense id '{bad_id}' must return 404 via Flask type converter"
        )


# ------------------------------------------------------------------ #
# Edge cases                                                          #
# ------------------------------------------------------------------ #

class TestDeleteExpenseEdgeCases:
    """
    Edge cases: deleting the only expense a user has, and confirming that
    the delete endpoint is not confused by a zero expense id.
    """

    def setup_method(self):
        self.email = _unique_email()
        self.user_id = None

    def teardown_method(self):
        if self.user_id:
            _delete_expenses_for_user(self.user_id)
            _delete_user(self.user_id)

    def test_delete_sole_expense_leaves_user_with_zero_expenses(self, client):
        """Deleting the only expense must leave the user with no expenses at all."""
        self.user_id = _register_and_login(client, self.email)
        expense_id = _seed_expense(self.user_id, description="Only expense")
        client.post(f"/expenses/{expense_id}/delete")
        conn = get_db()
        count = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (self.user_id,)
        ).fetchone()[0]
        conn.close()
        assert count == 0, (
            "User must have zero expenses after their only expense is deleted"
        )

    def test_delete_id_zero_returns_404(self, client):
        """Expense id 0 can never exist (AUTOINCREMENT starts at 1); must return 404."""
        self.user_id = _register_and_login(client, self.email)
        response = client.post("/expenses/0/delete")
        assert response.status_code == 404, (
            "Expense id 0 must return 404 as it can never be a valid row"
        )

    def test_delete_expense_with_null_description_succeeds(self, client):
        """An expense seeded without a description must be deletable."""
        self.user_id = _register_and_login(client, self.email)
        expense_id = _seed_expense(self.user_id, description=None)
        response = client.post(f"/expenses/{expense_id}/delete")
        assert response.status_code == 302, (
            "Deleting an expense with NULL description must succeed"
        )
        assert not _expense_exists(expense_id), (
            "Expense with NULL description must be removed from DB"
        )

    def test_delete_does_not_affect_other_users_expenses(self, client):
        """
        Deleting one user's expense must not touch expenses belonging to
        any other user in the system.
        """
        # Set up a bystander with their own expense
        bystander_email = _unique_email()
        bystander_id = _create_user_direct("Bystander", bystander_email)
        bystander_expense = _seed_expense(
            bystander_id, description="Bystander expense"
        )
        try:
            # Set up the active user and delete their own expense
            self.user_id = _register_and_login(client, self.email)
            my_expense = _seed_expense(self.user_id, description="My expense")
            client.post(f"/expenses/{my_expense}/delete")
            # Bystander's expense must be untouched
            assert _expense_exists(bystander_expense), (
                "Deleting one user's expense must not affect another user's expense"
            )
        finally:
            _delete_expenses_for_user(bystander_id)
            _delete_user(bystander_id)

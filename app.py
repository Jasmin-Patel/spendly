import functools
import math
import os
from calendar import monthrange
from datetime import date, datetime
from flask import (
    Flask,
    flash,
    render_template,
    request,
    redirect,
    url_for,
    session,
    abort,
)
from werkzeug.security import generate_password_hash, check_password_hash
from database.db import (
    get_db,
    init_db,
    seed_db,
    get_user_by_email,
    create_user,
    create_expense,
    get_expense_by_id,
    update_expense,
)
from database.queries import (
    get_user_by_id,
    get_summary_stats,
    get_recent_transactions,
    get_category_breakdown,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(32)

EXPENSE_CATEGORIES = [
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
]


def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated


with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Date-filter helpers                                                 #
# ------------------------------------------------------------------ #


def _parse_filter_date(val):
    try:
        datetime.strptime(val, "%Y-%m-%d")
        return val
    except (ValueError, TypeError):
        return None


def _months_ago_str(today, n):
    m = (today.month - n - 1) % 12 + 1
    y = today.year + (today.month - n - 1) // 12
    return date(y, m, min(today.day, monthrange(y, m)[1])).isoformat()


def _get_preset_dates():
    today = date.today()
    return {
        "today": today.isoformat(),
        "this_month": today.replace(day=1).isoformat(),
        "three_months": _months_ago_str(today, 3),
        "six_months": _months_ago_str(today, 6),
    }


def _resolve_date_filter(args, presets):
    date_from = _parse_filter_date(args.get("date_from"))
    date_to = _parse_filter_date(args.get("date_to"))
    if date_from and date_to and date_from > date_to:
        flash("Start date must be before end date.")
        date_from = date_to = None
    if not date_from and not date_to:
        active_preset = "all_time"
    elif date_from == presets["this_month"] and date_to == presets["today"]:
        active_preset = "this_month"
    elif date_from == presets["three_months"] and date_to == presets["today"]:
        active_preset = "last_3m"
    elif date_from == presets["six_months"] and date_to == presets["today"]:
        active_preset = "last_6m"
    else:
        active_preset = "custom"
    return date_from, date_to, active_preset


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #


@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        if session.get("user_id"):
            return redirect(url_for("profile"))
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    confirm = request.form.get("confirm_password", "")

    if not all([name, email, password, confirm]):
        return render_template("register.html", error="All fields are required.")
    if len(password) < 8:
        return render_template(
            "register.html", error="Password must be at least 8 characters."
        )
    if password != confirm:
        return render_template("register.html", error="Passwords do not match.")
    if get_user_by_email(email):
        return render_template(
            "register.html", error="An account with that email already exists."
        )

    create_user(name, email, generate_password_hash(password))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("user_id"):
            return redirect(url_for("profile"))
        return render_template("login.html")

    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not email or not password:
        return render_template("login.html", error="All fields are required.")

    user = get_user_by_email(email)
    if not user or not check_password_hash(user["password_hash"], password):
        return render_template("login.html", error="Invalid email or password.")

    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    return redirect(url_for("profile"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/profile")
@login_required
def profile():
    user_id = session["user_id"]
    presets = _get_preset_dates()
    date_from, date_to, active_preset = _resolve_date_filter(request.args, presets)

    return render_template(
        "profile.html",
        user=get_user_by_id(user_id),
        summary=get_summary_stats(user_id, date_from=date_from, date_to=date_to),
        transactions=get_recent_transactions(
            user_id, date_from=date_from, date_to=date_to
        ),
        categories=get_category_breakdown(
            user_id, date_from=date_from, date_to=date_to
        ),
        date_from=date_from,
        date_to=date_to,
        active_preset=active_preset,
        presets=presets,
    )


@app.route("/analytics")
@login_required
def analytics():
    return render_template("analytics.html")


@app.route("/expenses/add", methods=["GET", "POST"])
@login_required
def add_expense():
    if request.method == "GET":
        return render_template(
            "add_expense.html",
            today=date.today().isoformat(),
            categories=EXPENSE_CATEGORIES,
        )

    amount_raw = request.form.get("amount", "").strip()
    category = request.form.get("category", "")
    expense_date = request.form.get("date", "").strip()
    description = request.form.get("description", "").strip() or None

    try:
        amount = float(amount_raw)
        if amount <= 0 or not math.isfinite(amount):
            raise ValueError
    except ValueError:
        return render_template(
            "add_expense.html",
            error="Amount must be a positive number.",
            today=date.today().isoformat(),
            categories=EXPENSE_CATEGORIES,
            form_data=request.form,
        )

    if category not in EXPENSE_CATEGORIES:
        return render_template(
            "add_expense.html",
            error="Please select a valid category.",
            today=date.today().isoformat(),
            categories=EXPENSE_CATEGORIES,
            form_data=request.form,
        )

    try:
        parsed = datetime.strptime(expense_date, "%Y-%m-%d")
        if parsed.strftime("%Y-%m-%d") != expense_date:
            raise ValueError
    except ValueError:
        return render_template(
            "add_expense.html",
            error="Please enter a valid date.",
            today=date.today().isoformat(),
            categories=EXPENSE_CATEGORIES,
            form_data=request.form,
        )

    create_expense(session["user_id"], amount, category, expense_date, description)
    return redirect(url_for("profile"))


@app.route("/expenses/<int:expense_id>/edit", methods=["GET", "POST"])
@login_required
def edit_expense(expense_id):
    expense = get_expense_by_id(expense_id)
    if expense is None:
        abort(404)
    if expense["user_id"] != session["user_id"]:
        abort(403)

    if request.method == "GET":
        return render_template(
            "edit_expense.html",
            expense=expense,
            categories=EXPENSE_CATEGORIES,
            selected_category=expense["category"],
        )

    amount_raw = request.form.get("amount", "").strip()
    category = request.form.get("category", "")
    expense_date = request.form.get("date", "").strip()
    description = request.form.get("description", "").strip() or None

    def rerender(error):
        return render_template(
            "edit_expense.html",
            error=error,
            expense=expense,
            categories=EXPENSE_CATEGORIES,
            selected_category=request.form.get("category", ""),
            form_data=request.form,
        )

    try:
        amount = float(amount_raw)
        if amount <= 0 or not math.isfinite(amount):
            raise ValueError
    except ValueError:
        return rerender("Amount must be a positive number.")

    if category not in EXPENSE_CATEGORIES:
        return rerender("Please select a valid category.")

    try:
        parsed = datetime.strptime(expense_date, "%Y-%m-%d")
        if parsed.strftime("%Y-%m-%d") != expense_date:
            raise ValueError
    except ValueError:
        return rerender("Please enter a valid date.")

    update_expense(expense_id, session["user_id"], amount, category, expense_date, description)
    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(host="127.0.0.1", debug=True, port=5001)

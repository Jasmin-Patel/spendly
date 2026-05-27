import sqlite3
import os
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "spendly.db"
)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            email         TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            amount      REAL    NOT NULL,
            category    TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            description TEXT,
            created_at  TEXT    DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


def seed_db():
    conn = get_db()
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        conn.close()
        return

    conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Demo User", "demo@spendly.com", generate_password_hash("demo123")),
    )
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    conn.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        [
            (user_id, 12.50, "Food", "2026-05-01", "Lunch at cafe"),
            (user_id, 45.00, "Transport", "2026-05-02", "Monthly bus pass"),
            (user_id, 120.00, "Bills", "2026-05-03", "Electricity bill"),
            (user_id, 30.00, "Health", "2026-05-04", "Pharmacy"),
            (user_id, 18.00, "Entertainment", "2026-05-05", "Cinema ticket"),
            (user_id, 65.00, "Shopping", "2026-05-06", "Clothing"),
            (user_id, 9.99, "Food", "2026-05-07", "Coffee and snacks"),
            (user_id, 22.00, "Other", "2026-05-07", "Miscellaneous"),
        ],
    )
    conn.commit()
    conn.close()


def get_user_by_email(email):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return user


def create_user(name, email, password_hash):
    conn = get_db()
    conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (name, email, password_hash),
    )
    conn.commit()
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return user_id


def create_expense(user_id, amount, category, expense_date, description):
    conn = get_db()
    conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, category, expense_date, description),
    )
    conn.commit()
    conn.close()


def get_user_by_id(user_id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return user


def get_expense_summary(user_id):
    conn = get_db()

    row = conn.execute(
        "SELECT COUNT(*) AS total_count, COALESCE(SUM(amount), 0.0) AS total_amount "
        "FROM expenses WHERE user_id = ?",
        (user_id,),
    ).fetchone()

    top = conn.execute(
        "SELECT category FROM expenses WHERE user_id = ? "
        "GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1",
        (user_id,),
    ).fetchone()

    conn.close()
    return {
        "total_count": row["total_count"],
        "total_amount": row["total_amount"],
        "top_category": top["category"] if top else None,
    }

from datetime import datetime
from database.db import get_db


def get_user_by_id(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT name, email, created_at FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "name": row["name"],
        "email": row["email"],
        "member_since": datetime.strptime(
            row["created_at"], "%Y-%m-%d %H:%M:%S"
        ).strftime("%B %Y"),
    }


def get_summary_stats(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0.0) AS total "
        "FROM expenses WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    top = conn.execute(
        "SELECT category FROM expenses WHERE user_id = ? "
        "GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1",
        (user_id,)
    ).fetchone()
    conn.close()
    return {
        "total_spent":       row["total"],
        "transaction_count": row["cnt"],
        "top_category":      top["category"] if top else None,
    }


def get_recent_transactions(user_id, limit=10):
    conn = get_db()
    rows = conn.execute(
        "SELECT date, description, category, amount FROM expenses "
        "WHERE user_id = ? ORDER BY date DESC, id DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return [
        {
            "date":        r["date"],
            "description": r["description"],
            "category":    r["category"],
            "amount":      r["amount"],
        }
        for r in rows
    ]


def get_category_breakdown(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT category AS name, SUM(amount) AS amount FROM expenses "
        "WHERE user_id = ? GROUP BY category ORDER BY SUM(amount) DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    if not rows:
        return []
    total = sum(r["amount"] for r in rows)
    items = [
        {"name": r["name"], "amount": r["amount"], "pct": int(r["amount"] / total * 100)}
        for r in rows
    ]
    items[0]["pct"] += 100 - sum(i["pct"] for i in items)
    return items

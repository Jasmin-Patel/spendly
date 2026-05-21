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


def _date_where(user_id, date_from, date_to):
    conds  = ["user_id = ?"]
    params = [user_id]
    if date_from:
        conds.append("date >= ?")
        params.append(date_from)
    if date_to:
        conds.append("date <= ?")
        params.append(date_to)
    return " WHERE " + " AND ".join(conds), params


def get_summary_stats(user_id, date_from=None, date_to=None):
    conn = get_db()
    where, params = _date_where(user_id, date_from, date_to)

    row = conn.execute(
        "SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0.0) AS total "
        "FROM expenses" + where,
        params
    ).fetchone()
    top = conn.execute(
        "SELECT category FROM expenses" + where +
        " GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1",
        params
    ).fetchone()
    conn.close()
    return {
        "total_spent":       row["total"],
        "transaction_count": row["cnt"],
        "top_category":      top["category"] if top else None,
    }


def get_recent_transactions(user_id, limit=10, date_from=None, date_to=None):
    conn = get_db()
    where, params = _date_where(user_id, date_from, date_to)

    rows = conn.execute(
        "SELECT date, description, category, amount FROM expenses"
        + where + " ORDER BY date DESC, id DESC LIMIT ?",
        params + [limit]
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


def get_category_breakdown(user_id, date_from=None, date_to=None):
    conn = get_db()
    where, params = _date_where(user_id, date_from, date_to)

    rows = conn.execute(
        "SELECT category AS name, SUM(amount) AS amount FROM expenses"
        + where + " GROUP BY category ORDER BY SUM(amount) DESC",
        params
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

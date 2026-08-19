"""
Analytics router — admin-facing read-only summary of chat_logs.

GET /analytics/summary
  Returns 30-day aggregate stats, top questions, and recent interactions.
"""

from fastapi import APIRouter

from db import get_pool

router = APIRouter()

_PERIOD = "30 days"


@router.get("/summary")
async def analytics_summary():
    pool = await get_pool()

    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM chat_logs WHERE logged_at > NOW() - INTERVAL '{_PERIOD}'"
        )
        escalations = await conn.fetchval(
            f"SELECT COUNT(*) FROM chat_logs WHERE event_type = 'escalation' AND logged_at > NOW() - INTERVAL '{_PERIOD}'"
        )
        no_match = await conn.fetchval(
            f"SELECT COUNT(*) FROM chat_logs WHERE event_type = 'no_match' AND logged_at > NOW() - INTERVAL '{_PERIOD}'"
        )
        avg_duration = await conn.fetchval(
            f"SELECT ROUND(AVG(duration_ms)) FROM chat_logs WHERE logged_at > NOW() - INTERVAL '{_PERIOD}'"
        )
        top_rows = await conn.fetch(
            f"""
            SELECT message, COUNT(*) AS count
            FROM chat_logs
            WHERE logged_at > NOW() - INTERVAL '{_PERIOD}'
              AND event_type IN ('chat', 'no_match', 'empty_kb')
            GROUP BY message
            ORDER BY count DESC
            LIMIT 10
            """
        )
        recent_rows = await conn.fetch(
            """
            SELECT id::text, logged_at, user_id, message, event_type, duration_ms
            FROM chat_logs
            ORDER BY logged_at DESC
            LIMIT 20
            """
        )

    total = total or 0
    escalations = escalations or 0

    return {
        "period_days": 30,
        "total_chats": total,
        "escalation_count": escalations,
        "escalation_rate": round(escalations / total * 100, 1) if total else 0.0,
        "no_match_count": no_match or 0,
        "avg_duration_ms": int(avg_duration) if avg_duration else 0,
        "top_questions": [
            {"message": r["message"], "count": r["count"]} for r in top_rows
        ],
        "recent_logs": [
            {
                "id": r["id"],
                "logged_at": r["logged_at"].isoformat(),
                "user_id": r["user_id"],
                "message": r["message"],
                "event_type": r["event_type"],
                "duration_ms": r["duration_ms"],
            }
            for r in recent_rows
        ],
    }


@router.delete("/user/{user_id}/data")
async def delete_user_data(user_id: str):
    """
    GDPR / POPIA right to erasure.
    Deletes all chat_logs rows for the given user_id.
    Returns the number of rows deleted.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM chat_logs WHERE user_id = $1",
            user_id,
        )
    # asyncpg returns a status string like 'DELETE 5'
    deleted_rows = int(result.split()[-1]) if result else 0
    return {"user_id": user_id, "deleted_rows": deleted_rows}

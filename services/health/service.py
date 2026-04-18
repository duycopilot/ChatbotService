'''
Purpose: Business logic with health data
'''

from fastapi import Request


async def get_health_status(request: Request) -> dict:
    """Return service health and verify DB connectivity using lifecycle pool."""
    db_status = "down"
    overall_status = "ok"

    pool = getattr(request.app.state, "db_pool", None) or getattr(request.app.state, "pool", None)
    if pool is None:
        return {
            "status": "degraded",
            "services": {
                "api": "ok",
                "database": "down",
            },
            "error": "database pool is not initialized",
        }

    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        db_status = "ok"
    except Exception as exc:
        overall_status = "degraded"
        return {
            "status": overall_status,
            "services": {
                "api": "ok",
                "database": db_status,
            },
            "error": str(exc),
        }

    return {
        "status": overall_status,
        "services": {
            "api": "ok",
            "database": db_status,
        },
    }
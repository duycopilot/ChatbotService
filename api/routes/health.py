'''
Purpose:
- Check service whether it is alive or not
- Used for Docker/Kubernetes/load balancer
- Can be used for monitoring tools like Prometheus, Grafana, etc.
'''
from fastapi import APIRouter, Request
from services.health.service import get_health_status

router = APIRouter()


@router.get("", status_code=200)
async def health_check(request: Request):
    return await get_health_status(request)

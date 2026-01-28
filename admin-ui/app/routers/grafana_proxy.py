from __future__ import annotations

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.settings import get_settings

router = APIRouter()
settings = get_settings()

GRAFANA_BASE = settings.grafana_url.rstrip("/")


@router.api_route(
    "/grafana/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy_grafana(request: Request, path: str):
    target_url = f"{GRAFANA_BASE}/grafana/{path}"

    if request.query_params:
        target_url += f"?{request.query_params}"

    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)

    body = await request.body()

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body if body else None,
        )

    excluded_headers = {"content-encoding", "transfer-encoding", "connection"}
    response_headers = {
        k: v for k, v in response.headers.items() if k.lower() not in excluded_headers
    }

    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=response_headers,
        media_type=response.headers.get("content-type"),
    )

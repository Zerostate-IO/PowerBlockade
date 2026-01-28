from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.node import Node
from app.models.node_metrics import NodeMetrics
from app.routers.auth import get_current_user
from app.settings import get_settings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@dataclass
class HealthWarning:
    """A health warning with severity, message, and actionable remediation."""

    severity: str  # "critical", "warning", "info"
    title: str
    message: str
    remediation: str
    node_name: str | None = None  # None means global


# Thresholds for health warnings
CACHE_HIT_RATE_WARNING = 50.0  # Warn if cache hit rate below 50%
CACHE_HIT_RATE_CRITICAL = 20.0  # Critical if below 20%
SERVFAIL_RATE_WARNING = 5.0  # Warn if more than 5% SERVFAIL
TIMEOUT_RATE_WARNING = 2.0  # Warn if more than 2% timeouts
SLOW_ANSWER_RATE_WARNING = 10.0  # Warn if more than 10% slow answers
STALE_METRICS_MINUTES = 5  # Warn if metrics older than 5 minutes


def compute_health_warnings(
    node_data: list[dict],
) -> list[HealthWarning]:
    """Compute health warnings based on node metrics."""
    warnings: list[HealthWarning] = []
    now = datetime.now(timezone.utc)

    if not node_data:
        warnings.append(
            HealthWarning(
                severity="warning",
                title="No active nodes",
                message="No DNS resolver nodes are currently registered.",
                remediation="Add a secondary node via the Nodes page, or check if the primary "
                "node has registered itself correctly.",
            )
        )
        return warnings

    for item in node_data:
        node = item["node"]
        metrics = item["metrics"]

        if not metrics:
            warnings.append(
                HealthWarning(
                    severity="warning",
                    title="No metrics data",
                    message=f"Node '{node.name}' has not reported any metrics yet.",
                    remediation="Check that the sync-agent is running on this node and can "
                    "reach the primary API. Verify RECURSOR_API_URL is correct.",
                    node_name=node.name,
                )
            )
            continue

        # Check for stale metrics
        if metrics.ts:
            metrics_age = now - metrics.ts.replace(tzinfo=timezone.utc)
            if metrics_age > timedelta(minutes=STALE_METRICS_MINUTES):
                age_mins = int(metrics_age.total_seconds() / 60)
                warnings.append(
                    HealthWarning(
                        severity="warning",
                        title="Stale metrics",
                        message=f"Last metrics from '{node.name}' were {age_mins} minutes ago.",
                        remediation="Check that the sync-agent is running. Look for network "
                        "connectivity issues between this node and the primary.",
                        node_name=node.name,
                    )
                )

        # Cache hit rate
        total_queries = metrics.cache_hits + metrics.cache_misses
        if total_queries > 100:  # Only warn if meaningful sample size
            hit_rate = (metrics.cache_hits / total_queries) * 100
            if hit_rate < CACHE_HIT_RATE_CRITICAL:
                warnings.append(
                    HealthWarning(
                        severity="critical",
                        title="Very low cache hit rate",
                        message=f"Cache hit rate on '{node.name}' is only {hit_rate:.1f}%.",
                        remediation="This could indicate: (1) Recursor just restarted and cache "
                        "is warming up, (2) Cache size too small - increase 'max-cache-entries' "
                        "in recursor config, (3) Unusually diverse query patterns.",
                        node_name=node.name,
                    )
                )
            elif hit_rate < CACHE_HIT_RATE_WARNING:
                warnings.append(
                    HealthWarning(
                        severity="warning",
                        title="Low cache hit rate",
                        message=f"Cache hit rate on '{node.name}' is {hit_rate:.1f}%.",
                        remediation="Consider using the Precache feature to warm the cache with "
                        "frequently queried domains. Check if cache size is adequate.",
                        node_name=node.name,
                    )
                )

        # SERVFAIL rate
        if metrics.questions > 100:
            servfail_rate = (metrics.servfail_answers / metrics.questions) * 100
            if servfail_rate > SERVFAIL_RATE_WARNING:
                warnings.append(
                    HealthWarning(
                        severity="warning",
                        title="High SERVFAIL rate",
                        message=f"SERVFAIL rate on '{node.name}' is {servfail_rate:.1f}%.",
                        remediation="Check upstream DNS servers. Some domains may have broken "
                        "DNSSEC or misconfigured nameservers. Review the Failures page for "
                        "specific failing domains.",
                        node_name=node.name,
                    )
                )

        # Timeout rate
        if metrics.all_outqueries > 100:
            timeout_rate = (metrics.outgoing_timeouts / metrics.all_outqueries) * 100
            if timeout_rate > TIMEOUT_RATE_WARNING:
                warnings.append(
                    HealthWarning(
                        severity="warning",
                        title="High timeout rate",
                        message=f"Upstream timeout rate on '{node.name}' is {timeout_rate:.1f}%.",
                        remediation="Check network connectivity to upstream DNS servers. "
                        "Consider adding backup upstream servers in Forward Zones, or check "
                        "firewall rules that might be blocking outbound DNS.",
                        node_name=node.name,
                    )
                )

        # Slow answer rate
        total_answers = (
            metrics.answers_0_1
            + metrics.answers_1_10
            + metrics.answers_10_100
            + metrics.answers_100_1000
            + metrics.answers_slow
        )
        if total_answers > 100:
            slow_rate = (metrics.answers_slow / total_answers) * 100
            if slow_rate > SLOW_ANSWER_RATE_WARNING:
                warnings.append(
                    HealthWarning(
                        severity="info",
                        title="Many slow queries",
                        message=f"{slow_rate:.1f}% of answers on '{node.name}' took >1 second.",
                        remediation="This may be normal during cache warmup. Consider enabling "
                        "Precache for popular domains. Check if upstream servers are responsive.",
                        node_name=node.name,
                    )
                )

    return warnings


@router.get("/system", response_class=HTMLResponse)
def system_health(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    nodes = db.query(Node).filter(Node.status == "active").all()

    node_data = []
    for node in nodes:
        latest = (
            db.query(NodeMetrics)
            .filter(NodeMetrics.node_id == node.id)
            .order_by(NodeMetrics.ts.desc())
            .first()
        )
        node_data.append({"node": node, "metrics": latest})

    warnings = compute_health_warnings(node_data)

    settings = get_settings()

    return templates.TemplateResponse(
        "system.html",
        {
            "request": request,
            "user": user,
            "nodes": node_data,
            "warnings": warnings,
            "version": settings.pb_version,
            "git_sha": settings.pb_git_sha[:7]
            if len(settings.pb_git_sha) > 7
            else settings.pb_git_sha,
            "build_date": settings.pb_build_date,
        },
    )

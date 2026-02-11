from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.node import Node
from app.models.node_metrics import NodeMetrics
from app.models.settings import (
    get_health_cache_hit_critical,
    get_health_cache_hit_warning,
    get_health_servfail_warning,
    get_health_slow_warning,
    get_health_stale_minutes,
    get_health_timeout_warning,
)
from app.routers.auth import get_current_user
from app.settings import get_settings
from app.template_utils import get_templates

router = APIRouter()
templates = get_templates()


@dataclass
class HealthWarning:
    """A health warning with severity, message, and actionable remediation."""

    severity: str  # "critical", "warning", "info"
    title: str
    message: str
    remediation: str
    node_name: str | None = None  # None means global


@dataclass
class HealthThresholds:
    cache_hit_warning: float = 50.0
    cache_hit_critical: float = 20.0
    servfail_warning: float = 5.0
    timeout_warning: float = 2.0
    slow_warning: float = 10.0
    stale_minutes: int = 5


def load_health_thresholds(db) -> HealthThresholds:
    return HealthThresholds(
        cache_hit_warning=get_health_cache_hit_warning(db),
        cache_hit_critical=get_health_cache_hit_critical(db),
        servfail_warning=get_health_servfail_warning(db),
        timeout_warning=get_health_timeout_warning(db),
        slow_warning=get_health_slow_warning(db),
        stale_minutes=get_health_stale_minutes(db),
    )


def compute_health_warnings(
    node_data: list[dict],
    thresholds: HealthThresholds | None = None,
) -> list[HealthWarning]:
    if thresholds is None:
        thresholds = HealthThresholds()

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

        if node.last_seen:
            last_seen = node.last_seen
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            heartbeat_age = now - last_seen
            if heartbeat_age > timedelta(minutes=thresholds.stale_minutes):
                age_mins = int(heartbeat_age.total_seconds() / 60)
                warnings.append(
                    HealthWarning(
                        severity="warning",
                        title="Stale node heartbeat",
                        message=f"Node '{node.name}' last checked in {age_mins} minutes ago.",
                        remediation="Check that the sync-agent is running on this node and can "
                        "reach the primary API. Verify network connectivity.",
                        node_name=node.name,
                    )
                )

        # Check for stale metrics
        if metrics.ts:
            metrics_age = now - metrics.ts.replace(tzinfo=timezone.utc)
            if metrics_age > timedelta(minutes=thresholds.stale_minutes):
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
            if hit_rate < thresholds.cache_hit_critical:
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
            elif hit_rate < thresholds.cache_hit_warning:
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
            if servfail_rate > thresholds.servfail_warning:
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
            if timeout_rate > thresholds.timeout_warning:
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
            if slow_rate > thresholds.slow_warning:
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

    thresholds = load_health_thresholds(db)
    warnings = compute_health_warnings(node_data, thresholds)

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

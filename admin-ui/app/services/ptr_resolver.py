from __future__ import annotations

import ipaddress
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.client_resolver_rule import ClientResolverRule

PTR_CACHE_TTL_SECONDS = 3600
PTR_CACHE_ERROR_TTL_SECONDS = 300
PTR_TIMEOUT_SECONDS = 2.0


def ip_in_subnet(ip_str: str, subnet_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        network = ipaddress.ip_network(subnet_str, strict=False)
        return ip in network
    except ValueError:
        return False


def get_matching_rule(db: Session, ip: str) -> ClientResolverRule | None:
    rules = (
        db.query(ClientResolverRule)
        .filter(ClientResolverRule.enabled.is_(True))
        .order_by(ClientResolverRule.priority.asc())
        .all()
    )
    for rule in rules:
        if ip_in_subnet(ip, rule.subnet):
            return rule
    return None


def ptr_lookup(ip: str, nameserver: str, timeout: float = PTR_TIMEOUT_SECONDS) -> str | None:
    """
    Perform PTR lookup using the specified nameserver.
    Returns the hostname or None if lookup fails.
    """
    import dns.resolver
    import dns.reversename

    try:
        rev_name = dns.reversename.from_address(ip)
        resolver = dns.resolver.Resolver()

        ns_host = nameserver.split(":")[0]
        ns_port = int(nameserver.split(":")[1]) if ":" in nameserver else 53
        resolver.nameservers = [ns_host]
        resolver.port = ns_port
        resolver.lifetime = timeout

        answers = resolver.resolve(rev_name, "PTR")
        if answers:
            hostname = str(answers[0]).rstrip(".")
            return hostname
    except Exception:
        pass
    return None


def resolve_client_hostname(db: Session, ip: str, force: bool = False) -> str | None:
    """
    Resolve client hostname via PTR lookup using subnet-matched rules.
    Caches results in the Client table.
    """
    client = db.query(Client).filter(Client.ip == ip).one_or_none()

    if client is None:
        client = Client(ip=ip)
        db.add(client)
        db.flush()

    now = datetime.now(timezone.utc)

    if not force and client.rdns_last_resolved_at:
        age_seconds = (now - client.rdns_last_resolved_at).total_seconds()
        if client.rdns_name and age_seconds < PTR_CACHE_TTL_SECONDS:
            return client.rdns_name
        if client.rdns_last_error and age_seconds < PTR_CACHE_ERROR_TTL_SECONDS:
            return client.display_name

    if client.display_name:
        return client.display_name

    rule = get_matching_rule(db, ip)
    if rule is None:
        return None

    hostname = ptr_lookup(ip, rule.nameserver)

    client.rdns_last_resolved_at = now
    if hostname:
        client.rdns_name = hostname
        client.rdns_last_error = None
    else:
        client.rdns_last_error = f"PTR lookup failed via {rule.nameserver}"

    db.commit()

    return hostname or client.display_name


def bulk_resolve_clients(db: Session, ips: list[str]) -> dict[str, str | None]:
    """
    Resolve multiple client IPs in batch.
    Returns dict mapping IP -> hostname (or None).
    """
    results = {}
    for ip in ips:
        results[ip] = resolve_client_hostname(db, ip)
    return results

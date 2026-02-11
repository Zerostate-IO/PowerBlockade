from __future__ import annotations

import hashlib
import os
import re
import socket
import time
from pathlib import Path
from urllib.parse import urlparse

import requests


def getenv_required(key: str) -> str:
    v = os.getenv(key)
    if not v:
        raise RuntimeError(f"{key} is required")
    return v


def compute_file_checksum(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def get_local_ip(target_host: str) -> str | None:
    """Get the local IP address used to reach a target host."""
    try:
        # Create a socket and connect to determine our outbound IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        # Connect to the target on port 80 (doesn't actually send data for UDP)
        s.connect((target_host, 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def get_version() -> str:
    """Get the PowerBlockade version from environment."""
    return os.getenv("PB_VERSION", "unknown")


def write_if_changed(filepath: Path, content: str) -> bool:
    filepath.parent.mkdir(parents=True, exist_ok=True)

    if filepath.exists():
        existing = filepath.read_text(encoding="utf-8")
        if compute_file_checksum(existing) == compute_file_checksum(content):
            return False

    filepath.write_text(content, encoding="utf-8")
    return True


def clear_recursor_cache(recursor_url: str, api_key: str) -> tuple[bool, str]:
    try:
        r = requests.put(
            f"{recursor_url}/api/v1/servers/localhost/cache/flush",
            headers={"X-API-Key": api_key},
            params={"domain": "."},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            return True, f"flushed {data.get('count', 0)} entries"
        return False, f"status {r.status_code}: {r.text}"
    except Exception as e:
        return False, str(e)


def scrape_recursor_metrics(recursor_url: str) -> dict:
    try:
        r = requests.get(f"{recursor_url}/metrics", timeout=5)
        if r.status_code != 200:
            return {}

        metrics = {}
        for line in r.text.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            match = re.match(r"^pdns_recursor_(\w+)\s+([\d.]+)", line)
            if match:
                name = match.group(1)
                value = int(float(match.group(2)))
                metrics[name] = value

        return {
            "cache_hits": metrics.get("cache_hits", 0),
            "cache_misses": metrics.get("cache_misses", 0),
            "cache_entries": metrics.get("cache_entries", 0),
            "packetcache_hits": metrics.get("packetcache_hits", 0),
            "packetcache_misses": metrics.get("packetcache_misses", 0),
            "answers_0_1": metrics.get("answers0_1", 0),
            "answers_1_10": metrics.get("answers1_10", 0),
            "answers_10_100": metrics.get("answers10_100", 0),
            "answers_100_1000": metrics.get("answers100_1000", 0),
            "answers_slow": metrics.get("answers_slow", 0),
            "concurrent_queries": metrics.get("concurrent_queries", 0),
            "outgoing_timeouts": metrics.get("outgoing_timeouts", 0),
            "servfail_answers": metrics.get("servfail_answers", 0),
            "nxdomain_answers": metrics.get("nxdomain_answers", 0),
            "questions": metrics.get("questions", 0),
            "all_outqueries": metrics.get("all_outqueries", 0),
            "uptime_seconds": metrics.get("uptime_seconds", 0),
        }
    except Exception as e:
        print(f"metrics scrape error: {e}")
        return {}


def warm_domain(
    domain: str, dns_server: str = "127.0.0.1", port: int = 53
) -> int | None:
    try:
        import dns.resolver

        resolver = dns.resolver.Resolver()
        resolver.nameservers = [dns_server]
        resolver.port = port
        resolver.lifetime = 5.0

        answer = resolver.resolve(domain, "A")
        ttl = answer.rrset.ttl if answer.rrset else 300
        return ttl
    except Exception:
        return None


def warm_cache(
    domains: list[str], dns_server: str = "127.0.0.1", port: int = 53
) -> tuple[int, int]:
    success = 0
    failed = 0
    batch_size = 50
    batch_delay_ms = 100

    for i, domain in enumerate(domains):
        ttl = warm_domain(domain, dns_server, port)
        if ttl is not None:
            success += 1
        else:
            failed += 1

        if (i + 1) % batch_size == 0 and i + 1 < len(domains):
            time.sleep(batch_delay_ms / 1000.0)

    return success, failed


def fetch_precache_domains(
    primary_url: str, headers: dict, limit: int = 1000
) -> list[str]:
    try:
        r = requests.get(
            f"{primary_url}/api/node-sync/precache-domains",
            headers=headers,
            params={"limit": limit},
            timeout=30,
        )
        if r.status_code != 200:
            print(f"precache-domains fetch failed: {r.status_code}")
            return []

        data = r.json()
        return data.get("domains", [])
    except Exception as e:
        print(f"precache-domains error: {e}")
        return []


def run_precache_warming(
    primary_url: str,
    headers: dict,
    settings: dict,
    dns_server: str = "127.0.0.1",
) -> None:
    if settings.get("precache_enabled", "true").lower() != "true":
        return

    domain_count = int(settings.get("precache_domain_count", "1000"))
    domains = fetch_precache_domains(primary_url, headers, limit=domain_count)

    if not domains:
        print("no domains to warm")
        return

    print(f"warming {len(domains)} domains...")
    success, failed = warm_cache(domains, dns_server=dns_server, port=53)
    print(f"precache warming: {success}/{len(domains)} succeeded, {failed} failed")


def poll_and_execute_commands(
    primary_url: str,
    headers: dict,
    recursor_url: str,
    recursor_api_key: str,
) -> None:
    try:
        r = requests.get(
            f"{primary_url}/api/node-sync/commands", headers=headers, timeout=10
        )
        if r.status_code != 200:
            return

        data = r.json()
        commands = data.get("commands", [])

        for cmd in commands:
            cmd_id = cmd.get("id")
            cmd_type = cmd.get("command")
            success = False
            result = "unknown command"

            if cmd_type == "clear_cache":
                success, result = clear_recursor_cache(recursor_url, recursor_api_key)
                print(f"executed clear_cache: success={success} result={result}")

            try:
                requests.post(
                    f"{primary_url}/api/node-sync/commands/result",
                    headers=headers,
                    json={"command_id": cmd_id, "success": success, "result": result},
                    timeout=10,
                )
            except Exception as e:
                print(f"failed to report command result: {e}")

    except Exception as e:
        print(f"command poll error: {e}")


def sync_config(
    primary_url: str, headers: dict, rpz_dir: Path, fzones_path: Path
) -> tuple[bool, dict]:
    try:
        r = requests.get(
            f"{primary_url}/api/node-sync/config", headers=headers, timeout=30
        )
        if r.status_code != 200:
            print(f"config fetch failed: {r.status_code}")
            return False, {}

        data = r.json()
        changed = False

        for rpz_file in data.get("rpz_files", []):
            filename = rpz_file.get("filename")
            content = rpz_file.get("content")
            if filename and content:
                if write_if_changed(rpz_dir / filename, content):
                    print(f"updated RPZ: {filename}")
                    changed = True

        forward_zones = data.get("forward_zones", [])
        if forward_zones:
            lines = ["# Forward zones synced from primary", ""]
            for z in forward_zones:
                lines.append(f"{z['domain']}={z['servers']}")
            fz_content = "\n".join(lines) + "\n"
            if write_if_changed(fzones_path, fz_content):
                print("updated forward-zones.conf")
                changed = True

        settings = data.get("settings", {})
        return changed, settings
    except Exception as e:
        print(f"config sync error: {e}")
        return False, {}


def main() -> None:
    node_name = getenv_required("NODE_NAME")
    primary_url = getenv_required("PRIMARY_URL").rstrip("/")
    api_key = getenv_required("PRIMARY_API_KEY")
    recursor_api_key = os.getenv("RECURSOR_API_KEY", "")
    interval = int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "60"))
    config_sync_interval = int(os.getenv("CONFIG_SYNC_INTERVAL_SECONDS", "300"))
    recursor_url = os.getenv("RECURSOR_API_URL", "http://recursor:8082")
    rpz_dir = Path(os.getenv("RPZ_DIR", "/etc/pdns-recursor/rpz"))
    fzones_path = Path(
        os.getenv("FORWARD_ZONES_PATH", "/etc/pdns-recursor/forward-zones.conf")
    )

    headers = {"X-PowerBlockade-Node-Key": api_key}
    version = get_version()

    parsed_url = urlparse(primary_url)
    primary_host = parsed_url.hostname or "localhost"
    ip_address = get_local_ip(primary_host)

    def post(path: str, json: dict):
        url = f"{primary_url}{path}"
        return requests.post(url, headers=headers, json=json, timeout=10)

    while True:
        try:
            register_payload = {
                "name": node_name,
                "version": version,
                "ip_address": ip_address,
            }
            r = post("/api/node-sync/register", register_payload)
            if r.status_code < 300:
                print(f"registered as {node_name} (ip={ip_address}, version={version})")
                break
            raise RuntimeError(f"register failed: {r.status_code} {r.text}")
        except Exception as e:
            print(f"register error: {e}")
            time.sleep(5)

    last_config_sync = 0.0
    last_config_version = None
    last_precache_run = 0.0
    precache_interval = int(os.getenv("PRECACHE_INTERVAL_SECONDS", "300"))
    current_settings: dict = {}

    while True:
        config_version_from_primary = None
        try:
            heartbeat_payload = {"version": version}
            r = post("/api/node-sync/heartbeat", heartbeat_payload)
            if r.status_code >= 300:
                print(f"heartbeat failed: {r.status_code} {r.text}")
            else:
                data = r.json()
                config_version_from_primary = data.get("config_version")
                print(f"heartbeat ok (config_version={config_version_from_primary})")
        except Exception as e:
            print(f"heartbeat error: {e}")

        metrics = scrape_recursor_metrics(recursor_url)
        if metrics:
            try:
                r = post("/api/node-sync/metrics", metrics)
                if r.status_code >= 300:
                    print(f"metrics push failed: {r.status_code} {r.text}")
                else:
                    print("metrics push ok")
            except Exception as e:
                print(f"metrics push error: {e}")

        now = time.time()
        should_sync = False

        if (
            config_version_from_primary
            and config_version_from_primary != last_config_version
        ):
            print(
                f"config version changed: {last_config_version} -> {config_version_from_primary}"
            )
            should_sync = True

        if now - last_config_sync >= config_sync_interval:
            should_sync = True

        if should_sync:
            changed, settings = sync_config(primary_url, headers, rpz_dir, fzones_path)
            if changed:
                print("config changed, recursor will reload via polling")
            if settings:
                current_settings = settings
            last_config_sync = now
            last_config_version = config_version_from_primary

        if now - last_precache_run >= precache_interval:
            run_precache_warming(
                primary_url, headers, current_settings, dns_server="127.0.0.1"
            )
            last_precache_run = now

        poll_and_execute_commands(primary_url, headers, recursor_url, recursor_api_key)

        time.sleep(interval)


if __name__ == "__main__":
    main()

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import time
from pathlib import Path

import requests


def getenv_required(key: str) -> str:
    v = os.getenv(key)
    if not v:
        raise RuntimeError(f"{key} is required")
    return v


def compute_file_checksum(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def write_if_changed(filepath: Path, content: str) -> bool:
    filepath.parent.mkdir(parents=True, exist_ok=True)

    if filepath.exists():
        existing = filepath.read_text(encoding="utf-8")
        if compute_file_checksum(existing) == compute_file_checksum(content):
            return False

    filepath.write_text(content, encoding="utf-8")
    return True


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


def sync_config(
    primary_url: str, headers: dict, rpz_dir: Path, fzones_path: Path
) -> bool:
    try:
        r = requests.get(
            f"{primary_url}/api/node-sync/config", headers=headers, timeout=30
        )
        if r.status_code != 200:
            print(f"config fetch failed: {r.status_code}")
            return False

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

        return changed
    except Exception as e:
        print(f"config sync error: {e}")
        return False


def main() -> None:
    node_name = getenv_required("NODE_NAME")
    primary_url = getenv_required("PRIMARY_URL").rstrip("/")
    api_key = getenv_required("PRIMARY_API_KEY")
    interval = int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "60"))
    config_sync_interval = int(os.getenv("CONFIG_SYNC_INTERVAL_SECONDS", "300"))
    recursor_url = os.getenv("RECURSOR_API_URL", "http://recursor:8082")
    rpz_dir = Path(os.getenv("RPZ_DIR", "/etc/pdns-recursor/rpz"))
    fzones_path = Path(
        os.getenv("FORWARD_ZONES_PATH", "/etc/pdns-recursor/forward-zones.conf")
    )

    headers = {"X-PowerBlockade-Node-Key": api_key}

    def post(path: str, json: dict):
        url = f"{primary_url}{path}"
        return requests.post(url, headers=headers, json=json, timeout=10)

    while True:
        try:
            r = post("/api/node-sync/register", {"name": node_name})
            if r.status_code < 300:
                print(f"registered as {node_name}")
                break
            raise RuntimeError(f"register failed: {r.status_code} {r.text}")
        except Exception as e:
            print(f"register error: {e}")
            time.sleep(5)

    last_config_sync = 0.0

    while True:
        try:
            r = post("/api/node-sync/heartbeat", {})
            if r.status_code >= 300:
                print(f"heartbeat failed: {r.status_code} {r.text}")
            else:
                print("heartbeat ok")
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
        if now - last_config_sync >= config_sync_interval:
            if sync_config(primary_url, headers, rpz_dir, fzones_path):
                print("config changed, recursor will reload via polling")
            last_config_sync = now

        time.sleep(interval)


if __name__ == "__main__":
    main()

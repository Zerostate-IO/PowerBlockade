from __future__ import annotations

import os
import re
import time

import requests


def getenv_required(key: str) -> str:
    v = os.getenv(key)
    if not v:
        raise RuntimeError(f"{key} is required")
    return v


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


def main() -> None:
    node_name = getenv_required("NODE_NAME")
    primary_url = getenv_required("PRIMARY_URL").rstrip("/")
    api_key = getenv_required("PRIMARY_API_KEY")
    interval = int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "60"))
    recursor_url = os.getenv("RECURSOR_API_URL", "http://recursor:8082")

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

        time.sleep(interval)


if __name__ == "__main__":
    main()

from __future__ import annotations

import os
import time

import requests


def getenv_required(key: str) -> str:
    v = os.getenv(key)
    if not v:
        raise RuntimeError(f"{key} is required")
    return v


def main() -> None:
    node_name = getenv_required("NODE_NAME")
    primary_url = getenv_required("PRIMARY_URL").rstrip("/")
    api_key = getenv_required("PRIMARY_API_KEY")
    interval = int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "60"))

    headers = {"X-PowerBlockade-Node-Key": api_key}

    def post(path: str, json: dict):
        url = f"{primary_url}{path}"
        return requests.post(url, headers=headers, json=json, timeout=5)

    # Register
    while True:
        try:
            r = post("/api/node-sync/register", {"name": node_name})
            if r.status_code < 300:
                break
            raise RuntimeError(f"register failed: {r.status_code} {r.text}")
        except Exception as e:
            print(f"register error: {e}")
            time.sleep(5)

    # Heartbeat loop
    while True:
        try:
            r = post("/api/node-sync/heartbeat", {})
            if r.status_code >= 300:
                print(f"heartbeat failed: {r.status_code} {r.text}")
            else:
                print("heartbeat ok")
        except Exception as e:
            print(f"heartbeat error: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    main()

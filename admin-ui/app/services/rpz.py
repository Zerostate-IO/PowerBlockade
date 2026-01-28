from __future__ import annotations

import re
import time
from dataclasses import dataclass

_comment_re = re.compile(r"\s*(#|;).*$")


def _normalize_domain(s: str) -> str | None:
    s = s.strip().lower()
    s = _comment_re.sub("", s).strip()
    if not s:
        return None
    if s.startswith("||"):
        s = s[2:]
    if s.startswith("http://") or s.startswith("https://"):
        return None
    s = s.lstrip("*.")
    s = s.rstrip(".")
    if not s:
        return None
    # extremely cheap validation
    if " " in s or "\t" in s:
        return None
    if s.startswith("["):
        return None
    if "/" in s:
        return None
    return s


def parse_blocklist_text(text: str, fmt: str) -> set[str]:
    out: set[str] = set()
    fmt = fmt.strip().lower()

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("!"):
            continue

        if fmt == "hosts":
            # 0.0.0.0 example.com
            parts = _comment_re.sub("", line).split()
            if len(parts) >= 2:
                d = _normalize_domain(parts[1])
                if d:
                    out.add(d)
            continue

        # domains
        d = _normalize_domain(line)
        if d:
            out.add(d)

    return out


def render_rpz_zone(domains: set[str], *, policy_name: str) -> str:
    now = int(time.time())
    header = (
        f"$TTL 300\n"
        f"@ IN SOA localhost. hostmaster.localhost. {now} 3600 600 604800 300\n"
        f"@ IN NS localhost.\n"
        f"; policy: {policy_name}\n"
    )
    lines = [header]
    for d in sorted(domains):
        lines.append(f"{d}. CNAME .\n")
    return "".join(lines)


def render_rpz_whitelist(domains: set[str]) -> str:
    now = int(time.time())
    header = (
        f"$TTL 300\n"
        f"@ IN SOA localhost. hostmaster.localhost. {now} 3600 600 604800 300\n"
        f"@ IN NS localhost.\n"
        f"; whitelist (rpz-passthru)\n"
    )
    lines = [header]
    for d in sorted(domains):
        lines.append(f"{d}. CNAME rpz-passthru.\n")
    return "".join(lines)


@dataclass(frozen=True)
class RPZOutput:
    blocked_count: int
    allow_count: int

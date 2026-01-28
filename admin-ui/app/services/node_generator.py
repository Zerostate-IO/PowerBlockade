from __future__ import annotations

import io
import textwrap
import zipfile


def generate_secondary_package_zip(
    *,
    node_name: str,
    primary_url: str,
    node_api_key: str,
) -> bytes:
    safe_node = node_name.strip()
    primary_url = primary_url.rstrip("/")

    env = textwrap.dedent(
        f"""\
        NODE_NAME={safe_node}
        PRIMARY_URL={primary_url}
        PRIMARY_API_KEY={node_api_key}
        """
    )

    compose = textwrap.dedent(
        """\
        services:
          recursor:
            image: powerdns/pdns-recursor-51:latest
            restart: unless-stopped
            environment:
              TZ: ${TIMEZONE:-America/Los_Angeles}
              RECURSOR_API_KEY: ${RECURSOR_API_KEY:-change-me}
            ports:
              - "53:53/udp"
              - "53:53/tcp"
            volumes:
              - ./config/recursor.conf.template:/etc/pdns-recursor/recursor.conf.template:ro
              - ./config/rpz.lua:/etc/pdns-recursor/rpz.lua:ro
              - ./config/forward-zones.conf:/etc/pdns-recursor/forward-zones.conf:ro
              - ./rpz:/etc/pdns-recursor/rpz
              - dnstap-socket:/var/run/dnstap
            cap_add:
              - NET_BIND_SERVICE

          dnstap-processor:
            image: powerblockade/dnstap-processor:latest
            restart: unless-stopped
            environment:
              NODE_NAME: ${NODE_NAME}
              DNSTAP_SOCKET: /var/run/dnstap/dnstap.sock
              # In the Option-2 architecture, the processor will ship to PRIMARY_URL ingest.
              PRIMARY_URL: ${PRIMARY_URL}
              PRIMARY_API_KEY: ${PRIMARY_API_KEY}
            volumes:
              - dnstap-socket:/var/run/dnstap
            depends_on:
              - recursor

          sync-agent:
            image: powerblockade/sync-agent:latest
            restart: unless-stopped
            environment:
              NODE_NAME: ${NODE_NAME}
              PRIMARY_URL: ${PRIMARY_URL}
              PRIMARY_API_KEY: ${PRIMARY_API_KEY}
              HEARTBEAT_INTERVAL_SECONDS: ${HEARTBEAT_INTERVAL_SECONDS:-60}
            volumes:
              - ./config:/config
              - ./rpz:/rpz

        volumes:
          dnstap-socket:
        """
    )

    readme = textwrap.dedent(
        f"""\
        # PowerBlockade Secondary Node: {safe_node}

        ## Quick start

        1. Copy this folder to your secondary host
        2. Review `.env` (set PRIMARY_URL to the primary Admin UI URL)
        3. Run:

           docker compose up -d

        ## Notes

        - This node registers with the primary using `PRIMARY_API_KEY`.
        - OpenSearch remains internal-only on the primary (events/logs flow via the primary API).
        """
    )

    # Minimal config placeholders (sync-agent will later keep these updated)
    recursor_template = textwrap.dedent(
        """\
        # Rendered at container start; the sync-agent may replace this.
        local-address=0.0.0.0
        local-port=53
        allow-from=0.0.0.0/0, ::/0
        threads=2
        pdns-distributes-queries=yes
        lua-config-file=/etc/pdns-recursor/rpz.lua
        forward-zones-file=/etc/pdns-recursor/forward-zones.conf
        dnstap=yes
        dnstap-log-queries=yes
        dnstap-log-responses=yes
        dnstap-socket=/var/run/dnstap/dnstap.sock
        webserver=yes
        webserver-address=0.0.0.0
        webserver-port=8082
        webserver-allow-from=0.0.0.0/0
        api-key=${RECURSOR_API_KEY}
        prometheus-listen-address=0.0.0.0:9090
        """
    )

    rpz_lua = textwrap.dedent(
        """\
        rpzFile("/etc/pdns-recursor/rpz/blocklist-combined.rpz", {
          policyName = "blocklist-combined",
          defpol = Policy.NXDOMAIN,
        })

        rpzFile("/etc/pdns-recursor/rpz/whitelist.rpz", {
          policyName = "whitelist",
          defpol = Policy.PASSTHRU,
        })
        """
    )

    forward_zones = "# managed by primary\n"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("docker-compose.yml", compose)
        z.writestr(".env", env)
        z.writestr("README.md", readme)
        z.writestr("config/recursor.conf.template", recursor_template)
        z.writestr("config/rpz.lua", rpz_lua)
        z.writestr("config/forward-zones.conf", forward_zones)
        z.writestr("rpz/.gitkeep", "")

    return buf.getvalue()

from __future__ import annotations

import io
import textwrap
import zipfile


def generate_secondary_package_zip(
    *,
    node_name: str,
    primary_url: str,
    node_api_key: str,
    recursor_api_key: str = "",
    dnsdist_listen_address: str = "0.0.0.0",
) -> bytes:
    safe_node = node_name.strip()
    primary_url = primary_url.rstrip("/")

    env = textwrap.dedent(
        f"""\
        NODE_NAME={safe_node}
        PRIMARY_URL={primary_url}
        PRIMARY_API_KEY={node_api_key}
        RECURSOR_API_KEY={recursor_api_key or "change-me"}
        DNSDIST_LISTEN_ADDRESS={dnsdist_listen_address}
        HEARTBEAT_INTERVAL_SECONDS=60
        CONFIG_SYNC_INTERVAL_SECONDS=300
        """
    )

    compose = textwrap.dedent(
        """\
        services:
          dnsdist:
            image: powerdns/dnsdist-19:latest
            restart: unless-stopped
            ports:
              - "${DNSDIST_LISTEN_ADDRESS:-0.0.0.0}:53:53/udp"
              - "${DNSDIST_LISTEN_ADDRESS:-0.0.0.0}:53:53/tcp"
            volumes:
              - ./config/dnsdist.conf:/etc/dnsdist/dnsdist.conf:ro
              - dnstap-socket:/var/run/dnstap
            cap_add:
              - NET_BIND_SERVICE
            depends_on:
              - recursor

          recursor:
            image: powerdns/pdns-recursor-51:latest
            restart: unless-stopped
            environment:
              TZ: ${TIMEZONE:-America/Los_Angeles}
              RECURSOR_API_KEY: ${RECURSOR_API_KEY}
            expose:
              - "5300"
              - "8082"
            volumes:
              - ./config/recursor.conf:/etc/pdns-recursor/recursor.conf:ro
              - ./config/rpz.lua:/etc/pdns-recursor/rpz.lua:ro
              - ./config/forward-zones.conf:/etc/pdns-recursor/forward-zones.conf:ro
              - ./rpz:/etc/pdns-recursor/rpz
              - recursor-control-socket:/var/run/pdns-recursor

          recursor-reloader:
            image: powerdns/pdns-recursor-51:latest
            restart: unless-stopped
            entrypoint:
              - sh
              - -c
              - >-
                while true; do
                  rec_control --socket-dir=/var/run/pdns-recursor reload-zones || true;
                  rec_control --socket-dir=/var/run/pdns-recursor reload-lua-config || true;
                  rec_control --socket-dir=/var/run/pdns-recursor reload-fzones || true;
                  sleep 5;
                done
            volumes:
              - recursor-control-socket:/var/run/pdns-recursor
              - ./config/forward-zones.conf:/etc/pdns-recursor/forward-zones.conf:ro
            depends_on:
              - recursor

          dnstap-processor:
            image: powerblockade/dnstap-processor:latest
            restart: unless-stopped
            environment:
              NODE_NAME: ${NODE_NAME}
              DNSTAP_SOCKET: /var/run/dnstap/dnstap.sock
              PRIMARY_URL: ${PRIMARY_URL}
              PRIMARY_API_KEY: ${PRIMARY_API_KEY}
            volumes:
              - dnstap-socket:/var/run/dnstap
            depends_on:
              - dnsdist

          sync-agent:
            image: powerblockade/sync-agent:latest
            restart: unless-stopped
            environment:
              NODE_NAME: ${NODE_NAME}
              PRIMARY_URL: ${PRIMARY_URL}
              PRIMARY_API_KEY: ${PRIMARY_API_KEY}
              RECURSOR_API_KEY: ${RECURSOR_API_KEY}
              RECURSOR_API_URL: http://recursor:8082
              HEARTBEAT_INTERVAL_SECONDS: ${HEARTBEAT_INTERVAL_SECONDS:-60}
              CONFIG_SYNC_INTERVAL_SECONDS: ${CONFIG_SYNC_INTERVAL_SECONDS:-300}
              RPZ_DIR: /rpz
              FORWARD_ZONES_PATH: /config/forward-zones.conf
            volumes:
              - ./config:/config
              - ./rpz:/rpz
            depends_on:
              - recursor

        volumes:
          dnstap-socket:
          recursor-control-socket:
        """
    )

    readme = textwrap.dedent(
        f"""\
        # PowerBlockade Secondary Node: {safe_node}

        ## Quick start

        1. Copy this folder to your secondary host
        2. Review `.env`:
           - `PRIMARY_URL` - URL of the primary Admin UI (e.g., http://192.168.1.10:8080)
           - `RECURSOR_API_KEY` - Set a secure random key
           - `DNSDIST_LISTEN_ADDRESS` - Set to host's LAN IP if port 53 conflicts
        3. Run:

           docker compose up -d

        ## Architecture

        This is a headless mirror of the primary node:
        - **dnsdist** - Receives DNS queries, forwards to recursor, logs client IPs via dnstap
        - **recursor** - PowerDNS Recursor with RPZ blocking (synced from primary)
        - **dnstap-processor** - Ships query logs to primary
        - **sync-agent** - Pulls config from primary every 60s, executes commands

        No admin UI - all management is done via the primary.

        ## Sync behavior

        - Config (RPZ, forward zones) syncs within 60 seconds of changes on primary
        - Cache clear commands propagate within 60 seconds
        - Emergency blocking disable/pause takes effect within 60 seconds
        """
    )

    recursor_conf = textwrap.dedent(
        """\
        local-address=0.0.0.0
        local-port=5300
        allow-from=0.0.0.0/0, ::/0
        threads=2
        pdns-distributes-queries=yes
        lua-config-file=/etc/pdns-recursor/rpz.lua
        forward-zones-file=/etc/pdns-recursor/forward-zones.conf
        webserver=yes
        webserver-address=0.0.0.0
        webserver-port=8082
        webserver-allow-from=0.0.0.0/0
        api-key=$RECURSOR_API_KEY
        """
    )

    dnsdist_conf = textwrap.dedent(
        """\
        -- Secondary node dnsdist config
        -- dnstap for client IP attribution
        newServer({address="recursor:5300", name="recursor"})

        -- dnstap logging (CLIENT_RESPONSE only to avoid duplicates)
        dnstapFrameStreamServer("/var/run/dnstap/dnstap.sock", {logClientResponses=true})

        -- Listen on all interfaces (port binding via Docker)
        setLocal("0.0.0.0:53")
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
        z.writestr("config/recursor.conf", recursor_conf)
        z.writestr("config/dnsdist.conf", dnsdist_conf)
        z.writestr("config/rpz.lua", rpz_lua)
        z.writestr("config/forward-zones.conf", forward_zones)
        z.writestr("rpz/.gitkeep", "")

    return buf.getvalue()

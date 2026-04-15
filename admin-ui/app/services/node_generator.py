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
        POWERBLOCKADE_REPO=zerostate-io
        POWERBLOCKADE_VERSION=latest
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
            image: powerdns/dnsdist-20:2.0.3
            restart: unless-stopped
            environment:
              RECURSOR_WAIT_TIMEOUT_SECONDS: ${RECURSOR_WAIT_TIMEOUT_SECONDS:-30}
            ports:
              - "${DNSDIST_LISTEN_ADDRESS:-0.0.0.0}:53:53/udp"
              - "${DNSDIST_LISTEN_ADDRESS:-0.0.0.0}:53:53/tcp"
            volumes:
              - ./config/dnsdist.conf:/etc/dnsdist/dnsdist.conf:ro
              - dnstap-socket:/var/run/dnstap
            cap_add:
              - NET_BIND_SERVICE
            depends_on:
              recursor:
                condition: service_healthy
            healthcheck:
              test: ["CMD-SHELL", "bash -c 'echo >/dev/tcp/127.0.0.1/53' || exit 1"]
              interval: 10s
              timeout: 5s
              retries: 3
              start_period: 10s

          recursor:
            image: ghcr.io/${POWERBLOCKADE_REPO:-zerostate-io}/powerblockade-recursor:${POWERBLOCKADE_VERSION:-latest}
            restart: unless-stopped
            command: ["pdns_recursor", "--daemon=no", "--config-dir=/etc/pdns-recursor", "--enable-old-settings"]
            environment:
              TZ: ${TIMEZONE:-America/Los_Angeles}
              RECURSOR_API_KEY: ${RECURSOR_API_KEY}
            expose:
              - "5300"
              - "8082"
            healthcheck:
              test: ["CMD-SHELL", "rec_control --socket-dir=/var/run/pdns-recursor ping | grep -qi pong || exit 1"]
              interval: 10s
              timeout: 5s
              retries: 3
              start_period: 10s
            volumes:
              - ./config/recursor.conf:/etc/pdns-recursor/recursor.conf:ro
              - ./config/rpz.lua:/etc/pdns-recursor/rpz.lua:ro
              - ./config/forward-zones.conf:/etc/pdns-recursor/forward-zones.conf:ro
              - ./rpz:/etc/pdns-recursor/rpz
              - recursor-control-socket:/var/run/pdns-recursor

          recursor-reloader:
            image: ghcr.io/${POWERBLOCKADE_REPO:-zerostate-io}/powerblockade-recursor-reloader:${POWERBLOCKADE_VERSION:-latest}
            restart: unless-stopped
            environment:
              RELOADER_SOCKET_DIR: /var/run/pdns-recursor
              RELOADER_RPZ_DIR: /shared/rpz
              RELOADER_FORWARD_ZONES: /shared/forward-zones.conf
              RELOADER_DEBOUNCE_SECONDS: "2"
            volumes:
              - recursor-control-socket:/var/run/pdns-recursor
              - ./config/forward-zones.conf:/shared/forward-zones.conf:ro
              - ./rpz:/shared/rpz
            depends_on:
              recursor:
                condition: service_healthy

          dnstap-processor:
            image: ghcr.io/${POWERBLOCKADE_REPO:-zerostate-io}/powerblockade-dnstap-processor:${POWERBLOCKADE_VERSION:-latest}
            restart: unless-stopped
            environment:
              NODE_NAME: ${NODE_NAME}
              DNSTAP_SOCKET: /var/run/dnstap/dnstap.sock
              PRIMARY_URL: ${PRIMARY_URL}
              PRIMARY_API_KEY: ${PRIMARY_API_KEY}
              DNSTAP_LISTEN: "0.0.0.0:6000"
            volumes:
              - dnstap-socket:/var/run/dnstap
            depends_on:
              dnsdist:
                condition: service_healthy

          sync-agent:
            image: ghcr.io/${POWERBLOCKADE_REPO:-zerostate-io}/powerblockade-sync-agent:${POWERBLOCKADE_VERSION:-latest}
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
              recursor:
                condition: service_healthy

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

           docker compose -f docker-compose.ghcr.yml --profile secondary up -d

        ## Architecture

        This is a headless mirror of the primary node:
        - **dnsdist** - Receives DNS queries, forwards to recursor, logs client IPs via dnstap
        - **recursor** - PowerDNS Recursor with RPZ blocking (synced from primary)
        - **recursor-reloader** - Watches config files and reloads recursor on changes
        - **dnstap-processor** - Ships query logs to primary
        - **sync-agent** - Pulls config from primary every 300s, writes changed files

        No admin UI - all management is done via the primary.

        ## Sync behavior

        - Config (RPZ, forward zones) syncs within 300 seconds of changes on primary
        - Recursor reloads automatically when the reloader sidecar detects changed files
        - Cache clear commands propagate within 60 seconds
        - Emergency blocking disable/pause takes effect within 60 seconds
        """
    )

    recursor_conf = textwrap.dedent(
        f"""\
        local-address=0.0.0.0
        local-port=5300
        allow-from=0.0.0.0/0, ::/0
        threads=4
        pdns-distributes-queries=yes
        reuseport=yes
        max-cache-entries=2000000
        max-packetcache-entries=1000000
        packetcache-ttl=86400
        packetcache-negative-ttl=60
        packetcache-servfail-ttl=5
        lua-config-file=/etc/pdns-recursor/rpz.lua
        forward-zones-file=/etc/pdns-recursor/forward-zones.conf
        webserver=yes
        webserver-address=0.0.0.0
        webserver-port=8082
        webserver-allow-from=0.0.0.0/0
        api-key={recursor_api_key or "change-me"}
        """
    )

    dnsdist_conf = textwrap.dedent(
        """\
        -- Secondary node dnsdist config
        setLocal("0.0.0.0:53", { reusePort=true })
        newServer({address="recursor:5300", name="recursor", sockets=4, useClientSubnet=true})
        setServerPolicy(firstAvailable)

        local pc = newPacketCache(500000, {
          maxTTL=86400,
          minTTL=1,
          temporaryFailureTTL=5,
          staleTTL=60,
          dontAge=false,
          shuffle=true
        })
        getPool(""):setCache(pc)
        setStaleCacheEntriesTTL(60)

        local fs = newFrameStreamTcpLogger("dnstap-processor:6000", {
          bufferHint=65536,
          flushTimeout=1,
          outputQueueSize=64,
          queueNotifyThreshold=32,
          reopenInterval=5
        })
        addResponseAction(AllRule(), DnstapLogResponseAction("powerblockade-dnsdist", fs))
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
        z.writestr("docker-compose.ghcr.yml", compose)
        z.writestr(".env", env)
        z.writestr("README.md", readme)
        z.writestr("config/recursor.conf", recursor_conf)
        z.writestr("config/dnsdist.conf", dnsdist_conf)
        z.writestr("config/rpz.lua", rpz_lua)
        z.writestr("config/forward-zones.conf", forward_zones)
        z.writestr("rpz/.gitkeep", "")

    return buf.getvalue()

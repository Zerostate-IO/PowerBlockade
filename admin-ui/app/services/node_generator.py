from __future__ import annotations

import io
import secrets
import textwrap
import zipfile

from app.settings import get_settings


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

    # Per-package basic-auth password for the recursor webserver (/metrics
    # and /api/v1). Generated unconditionally - the release contract is
    # "never passwordless" - and never defaulted, so there is no
    # caller-supplied empty path. token_urlsafe's alphabet ([A-Za-z0-9_-])
    # is inside the charset the recursor image entrypoint accepts
    # ([A-Za-z0-9._~+=@-]); if a user later blanks the value in .env, the
    # entrypoint fail-safes to a random per-start password with a warning
    # rather than starting the webserver unauthenticated.
    recursor_web_password = secrets.token_urlsafe(24)

    env = textwrap.dedent(
        f"""\
        POWERBLOCKADE_REPO=zerostate-io
        POWERBLOCKADE_VERSION={get_settings().pb_version}
        NODE_NAME={safe_node}
        PRIMARY_URL={primary_url}
        PRIMARY_API_KEY={node_api_key}
        RECURSOR_API_KEY={recursor_api_key or "change-me"}
        RECURSOR_WEB_PASSWORD={recursor_web_password}
        DNSDIST_LISTEN_ADDRESS={dnsdist_listen_address}
        HEARTBEAT_INTERVAL_SECONDS=60
        CONFIG_SYNC_INTERVAL_SECONDS=300
        DOCKER_SUBNET=172.30.0.0/24
        RECURSOR_IP=172.30.0.10
        DNSTAP_PROCESSOR_IP=172.30.0.20
        """
    )

    compose = textwrap.dedent(
        """\
        services:
          init-permissions:
            image: busybox:1.38.0
            container_name: powerblockade-init-permissions
            command: sh -c "chown -R 1000:1000 /shared/rpz && chmod -R 775 /shared/rpz && touch /shared/rpz/.gitkeep && chown 1000:1000 /shared/forward-zones.conf && chmod 664 /shared/forward-zones.conf"
            volumes:
              - ./rpz:/shared/rpz
              - ./config/forward-zones.conf:/shared/forward-zones.conf
            restart: "no"

          dnsdist:
            image: powerdns/dnsdist-20:2.0.8
            restart: unless-stopped
            entrypoint: ["/docker-entrypoint.sh"]
            environment:
              RECURSOR_IP: ${RECURSOR_IP:-172.30.0.10}
              DNSTAP_PROCESSOR_IP: ${DNSTAP_PROCESSOR_IP:-172.30.0.20}
              RECURSOR_WAIT_TIMEOUT_SECONDS: ${RECURSOR_WAIT_TIMEOUT_SECONDS:-30}
            ports:
              - "${DNSDIST_LISTEN_ADDRESS:-0.0.0.0}:53:53/udp"
              - "${DNSDIST_LISTEN_ADDRESS:-0.0.0.0}:53:53/tcp"
            volumes:
              - ./config/dnsdist.conf.template:/etc/dnsdist/dnsdist.conf.template:ro
              - ./docker-entrypoint.sh:/docker-entrypoint.sh:ro
              - dnstap-socket:/var/run/dnstap
            cap_add:
              - NET_BIND_SERVICE
            networks:
              - default
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
              # Basic-auth password for the metrics webserver (/metrics
              # authenticates with the WEBserver password, never the
              # api-key). No default: an unset/invalid value makes the image
              # entrypoint generate a random per-start password with a
              # warning instead of starting passwordless.
              RECURSOR_WEB_PASSWORD: ${RECURSOR_WEB_PASSWORD:-}
            expose:
              - "5300"
              - "8082"
            networks:
              default:
                ipv4_address: ${RECURSOR_IP:-172.30.0.10}
            healthcheck:
              test: ["CMD-SHELL", "rec_control --socket-dir=/var/run/pdns-recursor ping | grep -qi pong || exit 1"]
              interval: 10s
              timeout: 5s
              retries: 3
              start_period: 10s
            volumes:
              # Rendered to /etc/pdns-recursor/recursor.conf by the image
              # entrypoint, which substitutes ${RECURSOR_API_KEY} and
              # ${RECURSOR_WEB_PASSWORD} (see recursor/docker-entrypoint.sh
              # in the repo - same contract as the primary stack).
              - ./config/recursor.conf.template:/etc/pdns-recursor/recursor.conf.template:ro
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
              # Client subnets flagged is_internal (excluded from analytics).
              # Defaults to the docker subnet; comma-separated to add more.
              INTERNAL_SUBNETS: ${INTERNAL_SUBNETS:-${DOCKER_SUBNET:-172.30.0.0/24}}
            networks:
              default:
                ipv4_address: ${DNSTAP_PROCESSOR_IP:-172.30.0.20}
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
              # /metrics requires HTTP basic auth with the webserver
              # password (any username); the api-key does not authorize it.
              RECURSOR_WEB_PASSWORD: ${RECURSOR_WEB_PASSWORD:-}
              RECURSOR_API_URL: http://recursor:8082
              HEARTBEAT_INTERVAL_SECONDS: ${HEARTBEAT_INTERVAL_SECONDS:-60}
              CONFIG_SYNC_INTERVAL_SECONDS: ${CONFIG_SYNC_INTERVAL_SECONDS:-300}
              RPZ_DIR: /rpz
              FORWARD_ZONES_PATH: /config/forward-zones.conf
            volumes:
              - ./config:/config
              - ./rpz:/rpz
              - metrics-buffer:/var/lib/powerblockade
            depends_on:
              init-permissions:
                condition: service_completed_successfully
              recursor:
                condition: service_healthy

        volumes:
          dnstap-socket:
          recursor-control-socket:
          metrics-buffer:

        networks:
          default:
            ipam:
              config:
                - subnet: ${DOCKER_SUBNET:-172.30.0.0/24}
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
           - `RECURSOR_WEB_PASSWORD` - Basic-auth password for the recursor metrics
             webserver (pre-generated; replace to rotate, then restart recursor
             and sync-agent)
           - `DNSDIST_LISTEN_ADDRESS` - Set to host's LAN IP if port 53 conflicts
           - `DOCKER_SUBNET` - If changed, also update `webserver-allow-from` in
             `config/recursor.conf.template` (it only admits the default
             172.30.0.0/16 compose network)
        3. Run:

           docker compose -f docker-compose.ghcr.yml up -d

        ## Architecture

        This is a headless mirror of the primary node:
        - **dnsdist** - Receives DNS queries, forwards to recursor, logs client IPs via dnstap
        - **recursor** - PowerDNS Recursor with RPZ blocking (synced from primary)
        - **recursor-reloader** - Watches config files and reloads recursor on changes
        - **dnstap-processor** - Ships query logs to primary
        - **sync-agent** - Pulls config from primary every 300s, writes changed files,
          scrapes authenticated recursor metrics

        No admin UI - all management is done via the primary.

        ## Sync behavior

        - Config (RPZ, forward zones) syncs within 300 seconds of changes on primary
        - Recursor reloads automatically when the reloader sidecar detects changed files
        - Cache clear commands propagate within 60 seconds
        - Emergency blocking disable/pause takes effect within 60 seconds
        """
    )

    # Rendered by the recursor image entrypoint (/docker-entrypoint.sh,
    # same contract as the primary stack), which substitutes
    # ${RECURSOR_API_KEY} and ${RECURSOR_WEB_PASSWORD} at container start.
    # Secrets live only in .env (mode 0600) and container env - never here.
    recursor_conf_template = textwrap.dedent(
        """\
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

        # API / metrics webserver. Port 8082 is not published to the host;
        # only in-network services (sync-agent) reach it. Auth matrix
        # (verified on powerdns/pdns-recursor-53:5.3.10): /metrics requires
        # HTTP basic auth with webserver-password (any username; the api-key
        # does NOT authorize /metrics), and an EMPTY webserver-password
        # leaves the whole webserver unauthenticated - the entrypoint
        # therefore substitutes a random password with a warning when
        # RECURSOR_WEB_PASSWORD is unset or invalid. Sources outside
        # webserver-allow-from are dropped at the TCP level; the allow-from
        # covers this package's compose network (DOCKER_SUBNET default
        # 172.30.0.0/24) - update it if you change DOCKER_SUBNET.
        webserver=yes
        webserver-address=0.0.0.0
        webserver-port=8082
        webserver-allow-from=172.30.0.0/16
        api-key=${RECURSOR_API_KEY}
        webserver-password=${RECURSOR_WEB_PASSWORD}
        """
    )

    dnsdist_conf_template = textwrap.dedent(
        """\
        -- Secondary node dnsdist config
        setLocal('0.0.0.0:53', { reusePort=true })
        newServer({
            address='${RECURSOR_IP}:5300',
            name='recursor',
            sockets=4,
            -- ECS is dead overhead: the recursor ignores incoming ECS by
            -- default, so useClientSubnet=true only added per-miss cost.
            -- Experiment E2; rollback: set useClientSubnet=true.
            useClientSubnet=false
        })
        setServerPolicy(firstAvailable)

        local pc = newPacketCache(500000, {
          maxTTL=86400,
          minTTL=1,
          temporaryFailureTTL=5,
          -- Experiment E4; rollback: 60.
          staleTTL=300,
          dontAge=false,
          shuffle=true,
          -- Required for staleTTL to deliver: without it the cache cleaner
          -- purges expired entries on its ~60s cadence while backends are
          -- down. Experiment E4; rollback: remove keepStaleData.
          keepStaleData=true
        })
        getPool(''):setCache(pc)
        -- Experiment E4; rollback: 60.
        setStaleCacheEntriesTTL(300)

        local fs = newFrameStreamTcpLogger('${DNSTAP_PROCESSOR_IP}:6000', {
          bufferHint=65536,
          flushTimeout=1,
          outputQueueSize=64,
          queueNotifyThreshold=32,
          reopenInterval=5
        })
        addResponseAction(AllRule(), DnstapLogResponseAction('powerblockade-dnsdist', fs))
        """
    )

    docker_entrypoint = textwrap.dedent(
        """\
        #!/bin/bash
        set -e

        RECURSOR_IP="${RECURSOR_IP:-172.30.0.10}"
        DNSTAP_PROCESSOR_IP="${DNSTAP_PROCESSOR_IP:-172.30.0.20}"

        sed -e "s/\\${RECURSOR_IP}/$RECURSOR_IP/g" \\
            -e "s/\\${DNSTAP_PROCESSOR_IP}/$DNSTAP_PROCESSOR_IP/g" \\
            /etc/dnsdist/dnsdist.conf.template > /tmp/dnsdist.conf

        echo "Generated dnsdist.conf with RECURSOR_IP=$RECURSOR_IP, DNSTAP_PROCESSOR_IP=$DNSTAP_PROCESSOR_IP"

        # Wait for recursor to be reachable; fail closed so Docker retries
        timeout=${RECURSOR_WAIT_TIMEOUT_SECONDS:-30}
        elapsed=0
        recursor_ready=false
        while [ $elapsed -lt $timeout ]; do
            if bash -c "echo >/dev/tcp/$RECURSOR_IP/5300" 2>/dev/null; then
                echo "recursor is ready (${elapsed}s)"
                recursor_ready=true
                break
            fi
            sleep 1
            elapsed=$((elapsed + 1))
        done

        if [ "$recursor_ready" != "true" ]; then
            echo "ERROR: recursor not ready after ${timeout}s; refusing to start dnsdist without a backend" >&2
            exit 1
        fi

        exec dnsdist --supervised -C /tmp/dnsdist.conf
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

    def _entry(name: str, content: str, mode: int) -> zipfile.ZipInfo:
        """Zip entry with explicit permissions.

        Default writestr() entries unpack with restrictive modes (0600) which
        breaks containers running as non-root users (dnsdist runs as 'pdns',
        sync-agent as uid 1000) - observed on the bowlister v0.8.0 deploy.
        """
        info = zipfile.ZipInfo(name)
        info.external_attr = (mode & 0xFFFF) << 16
        return info

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(_entry("docker-compose.ghcr.yml", compose, 0o644), compose)
        z.writestr(_entry(".env", env, 0o600), env)  # secrets: owner-only
        z.writestr(_entry("README.md", readme, 0o644), readme)
        z.writestr(
            _entry("config/recursor.conf.template", recursor_conf_template, 0o644),
            recursor_conf_template,
        )
        z.writestr(
            _entry("config/dnsdist.conf.template", dnsdist_conf_template, 0o644),
            dnsdist_conf_template,
        )
        z.writestr(_entry("docker-entrypoint.sh", docker_entrypoint, 0o755), docker_entrypoint)
        z.writestr(_entry("config/rpz.lua", rpz_lua, 0o644), rpz_lua)
        z.writestr(_entry("config/forward-zones.conf", forward_zones, 0o664), forward_zones)
        z.writestr(_entry("rpz/", "", 0o775), "")
        z.writestr(_entry("rpz/.gitkeep", "", 0o664), "")

    return buf.getvalue()

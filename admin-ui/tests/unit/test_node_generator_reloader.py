"""Tests for node_generator secondary package output.

Verifies that generated ZIP packages use the official GHCR compose contract
with the unified recursor-reloader sidecar image and static-IP networking.
"""

from __future__ import annotations

import io
import re
import zipfile

import yaml

from app.services.node_generator import generate_secondary_package_zip


def _make_zip(**kwargs: str) -> zipfile.ZipFile:
    defaults = dict(
        node_name="test-node",
        primary_url="http://primary:8080",
        node_api_key="node-key-123",
        recursor_api_key="recursor-key-456",
    )
    defaults.update(kwargs)
    data = generate_secondary_package_zip(**defaults)  # type: ignore[arg-type]
    return zipfile.ZipFile(io.BytesIO(data))


def _env_value(env: str, key: str) -> str:
    """Return the raw value of KEY= from a dotenv body ("" if absent)."""
    for line in env.splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return ""


class TestComposeFileName:
    """Verify the authoritative compose file name in the ZIP."""

    def test_zip_contains_docker_compose_ghcr_yml(self) -> None:
        z = _make_zip()
        assert "docker-compose.ghcr.yml" in z.namelist()

    def test_zip_does_not_contain_legacy_compose(self) -> None:
        z = _make_zip()
        assert "docker-compose.yml" not in z.namelist()


class TestReloaderSidecar:
    """Verify the reloader sidecar uses the official GHCR image."""

    def test_reloader_uses_ghcr_image(self) -> None:
        z = _make_zip()
        compose = z.read("docker-compose.ghcr.yml").decode()
        assert "ghcr.io/" in compose
        assert "powerblockade-recursor-reloader" in compose

    def test_reloader_no_inline_shell_loop(self) -> None:
        z = _make_zip()
        compose = z.read("docker-compose.ghcr.yml").decode()
        # No sleep-based polling loop
        assert "sleep 1" not in compose
        assert "sleep 5" not in compose
        # No sentinel/signal file references
        assert ".reload-trigger" not in compose

    def test_reloader_uses_service_healthy_dependency(self) -> None:
        z = _make_zip()
        compose = z.read("docker-compose.ghcr.yml").decode()
        # The reloader should depend on recursor being healthy
        reloader_section = compose[compose.index("recursor-reloader:") :]
        assert "condition: service_healthy" in reloader_section

    def test_reloader_has_env_config(self) -> None:
        z = _make_zip()
        compose = z.read("docker-compose.ghcr.yml").decode()
        reloader_section = compose[compose.index("recursor-reloader:") :]
        assert "RELOADER_SOCKET_DIR" in reloader_section
        assert "RELOADER_RPZ_DIR" in reloader_section
        assert "RELOADER_FORWARD_ZONES" in reloader_section
        assert "RELOADER_DEBOUNCE_SECONDS" in reloader_section

    def test_no_runtime_apt_get(self) -> None:
        z = _make_zip()
        compose = z.read("docker-compose.ghcr.yml").decode()
        assert "apt-get" not in compose

    def test_no_entrypoint_shell_script(self) -> None:
        z = _make_zip()
        compose = z.read("docker-compose.ghcr.yml").decode()
        reloader_section = compose[compose.index("recursor-reloader:") :]
        before_dnstop = reloader_section.split("dnstap-processor:")[0]
        assert "entrypoint:" not in before_dnstop
        assert "shell:" not in before_dnstop


class TestStaticIPContract:
    """Verify generated packages use IP-literal dnsdist backends and static-IP networking.

    This catches the bowlister rollback bug: dnsdist rejects hostname-based
    newServer() addresses like 'recursor:5300'.
    """

    def test_dnsdist_template_uses_ip_literal_placeholders(self) -> None:
        z = _make_zip()
        template = z.read("config/dnsdist.conf.template").decode()
        # Must use ${RECURSOR_IP}:5300, not recursor:5300
        assert "${RECURSOR_IP}:5300" in template
        assert "${DNSTAP_PROCESSOR_IP}:6000" in template
        # Must NOT contain hostname-based references
        assert 'address="recursor:5300"' not in template
        assert "recursor:5300" not in template
        assert "dnstap-processor:6000" not in template

    def test_dnsdist_no_hostname_backend_anywhere(self) -> None:
        """No generated file should contain a hostname-based dnsdist backend."""
        z = _make_zip()
        for name in z.namelist():
            content = z.read(name).decode(errors="replace")
            assert "recursor:5300" not in content, (
                f"{name} contains hostname-based dnsdist backend 'recursor:5300'"
            )

    def test_env_contains_static_ip_vars(self) -> None:
        z = _make_zip()
        env = z.read(".env").decode()
        assert "DOCKER_SUBNET=" in env
        assert "RECURSOR_IP=" in env
        assert "DNSTAP_PROCESSOR_IP=" in env
        # Verify safe defaults match repo contract
        assert "DOCKER_SUBNET=172.30.0.0/24" in env
        assert "RECURSOR_IP=172.30.0.10" in env
        assert "DNSTAP_PROCESSOR_IP=172.30.0.20" in env

    def test_compose_has_static_ip_assignments(self) -> None:
        z = _make_zip()
        compose = z.read("docker-compose.ghcr.yml").decode()
        # recursor must have ipv4_address
        recursor_section = compose[compose.index("recursor:") :]
        recursor_before_reloader = recursor_section.split("recursor-reloader:")[0]
        assert "ipv4_address:" in recursor_before_reloader
        assert "${RECURSOR_IP:-172.30.0.10}" in recursor_before_reloader
        # dnstap-processor must have ipv4_address
        dnstap_section = compose[compose.index("dnstap-processor:") :]
        assert "ipv4_address:" in dnstap_section
        assert "${DNSTAP_PROCESSOR_IP:-172.30.0.20}" in dnstap_section

    def test_compose_has_network_definition(self) -> None:
        z = _make_zip()
        compose = z.read("docker-compose.ghcr.yml").decode()
        assert "networks:" in compose
        assert "ipam:" in compose
        assert "subnet:" in compose
        assert "${DOCKER_SUBNET:-172.30.0.0/24}" in compose

    def test_dnsdist_uses_entrypoint_with_template(self) -> None:
        z = _make_zip()
        compose = z.read("docker-compose.ghcr.yml").decode()
        # dnsdist service must use custom entrypoint that generates conf from template
        dnsdist_section = compose[compose.index("dnsdist:") :]
        dnsdist_before_recursor = dnsdist_section.split("recursor:")[0]
        assert 'entrypoint: ["/docker-entrypoint.sh"]' in dnsdist_before_recursor
        assert "dnsdist.conf.template" in dnsdist_before_recursor
        assert "docker-entrypoint.sh" in dnsdist_before_recursor

    def test_entrypoint_substitutes_ip_placeholders(self) -> None:
        z = _make_zip()
        entrypoint = z.read("docker-entrypoint.sh").decode()
        # Must sed-substitute RECURSOR_IP and DNSTAP_PROCESSOR_IP
        assert "RECURSOR_IP" in entrypoint
        assert "DNSTAP_PROCESSOR_IP" in entrypoint
        assert "sed" in entrypoint
        assert "dnsdist.conf.template" in entrypoint
        assert "/tmp/dnsdist.conf" in entrypoint
        # Must exec dnsdist with the generated config
        assert "exec dnsdist --supervised -C /tmp/dnsdist.conf" in entrypoint

    def test_compose_dnsdist_passes_ip_env_vars(self) -> None:
        z = _make_zip()
        compose = z.read("docker-compose.ghcr.yml").decode()
        dnsdist_section = compose[compose.index("dnsdist:") :]
        dnsdist_before_recursor = dnsdist_section.split("recursor:")[0]
        assert "RECURSOR_IP:" in dnsdist_before_recursor
        assert "DNSTAP_PROCESSOR_IP:" in dnsdist_before_recursor


class TestReadmeContent:
    """Verify the README uses the official startup command."""

    def test_readme_uses_ghcr_compose_command(self) -> None:
        z = _make_zip()
        readme = z.read("README.md").decode()
        assert "docker compose -f docker-compose.ghcr.yml" in readme
        # The generated compose defines no profiles, so no --profile flag
        assert "--profile secondary" not in readme

    def test_readme_no_legacy_command(self) -> None:
        z = _make_zip()
        readme = z.read("README.md").decode()
        # Should not contain bare "docker compose up -d" without -f flag
        lines = readme.splitlines()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("docker compose"):
                assert "-f docker-compose.ghcr.yml" in stripped, (
                    f"Found docker compose command without -f flag: {stripped}"
                )

    def test_readme_no_sentinel_references(self) -> None:
        z = _make_zip()
        readme = z.read("README.md").decode()
        assert ".reload-trigger" not in readme
        assert "sentinel" not in readme.lower()
        assert "sleep" not in readme

    def test_readme_mentions_reloader_sidecar(self) -> None:
        z = _make_zip()
        readme = z.read("README.md").decode()
        assert "recursor-reloader" in readme

    def test_readme_describes_watch_behavior(self) -> None:
        z = _make_zip()
        readme = z.read("README.md").decode()
        assert (
            "reloader sidecar" in readme
            or "watches" in readme.lower()
            or "detects" in readme.lower()
        )


class TestZipStructure:
    """Verify overall ZIP structure."""

    def test_zip_contains_required_files(self) -> None:
        z = _make_zip()
        names = z.namelist()
        assert "docker-compose.ghcr.yml" in names
        assert ".env" in names
        assert "README.md" in names
        # The package ships a conf TEMPLATE, not a static conf: the recursor
        # image entrypoint renders it at container start so
        # webserver-password/api-key come from env, never from a file that
        # sits world-readable in the package (release auth contract).
        assert "config/recursor.conf.template" in names
        assert "config/dnsdist.conf.template" in names
        assert "docker-entrypoint.sh" in names
        assert "config/rpz.lua" in names
        assert "config/forward-zones.conf" in names
        assert "rpz/.gitkeep" in names

    def test_zip_does_not_contain_static_dnsdist_conf(self) -> None:
        """Static dnsdist.conf is replaced by template + entrypoint."""
        z = _make_zip()
        assert "config/dnsdist.conf" not in z.namelist()

    def test_env_contains_node_config(self) -> None:
        z = _make_zip(node_name="mynode", primary_url="http://10.0.0.1:8080")
        env = z.read(".env").decode()
        assert "NODE_NAME=mynode" in env
        assert "PRIMARY_URL=http://10.0.0.1:8080" in env

    def test_all_ghcr_services_use_version_tag(self) -> None:
        z = _make_zip()
        compose = z.read("docker-compose.ghcr.yml").decode()
        # All ghcr.io images should reference the version variable
        ghcr_lines = [line for line in compose.splitlines() if "ghcr.io/" in line]
        for line in ghcr_lines:
            assert "POWERBLOCKADE_VERSION" in line, (
                f"GHCR image line missing version variable: {line}"
            )

    def test_env_embeds_release_version_not_latest(self) -> None:
        """Generated .env must pin the app's own release version, not 'latest'."""
        from app.settings import get_settings

        z = _make_zip()
        env = z.read(".env").decode()
        expected = f"POWERBLOCKADE_VERSION={get_settings().pb_version}"
        assert expected in env, f"expected {expected!r} in .env"
        assert "POWERBLOCKADE_VERSION=latest" not in env
        # Sanity: it must look like a semver tag, not a stale fixed value
        version = get_settings().pb_version
        assert version.startswith("v") and version.count(".") == 2

    def test_compose_pins_dnsdist_patch(self) -> None:
        """The embedded dnsdist must be version-pinned (security advisory line)."""
        z = _make_zip()
        compose = z.read("docker-compose.ghcr.yml").decode()
        assert "powerdns/dnsdist-20:2.0.8" in compose
        assert "dnsdist-20:latest" not in compose

    def test_entrypoint_fails_closed_without_backend(self) -> None:
        """dnsdist must refuse to start when the recursor is not ready."""
        z = _make_zip()
        entrypoint = z.read("docker-entrypoint.sh").decode()
        # The fail-closed guard: ready flag checked, then exit 1 before exec
        assert 'if [ "$recursor_ready" != "true" ]; then' in entrypoint
        assert "refusing to start dnsdist without a backend" in entrypoint
        assert "exit 1" in entrypoint
        # The timeout loop must track readiness, not just sleep through it
        assert "recursor_ready=true" in entrypoint

    def test_compose_has_metrics_buffer_volume(self) -> None:
        """sync-agent metrics buffer must survive container recreation."""
        z = _make_zip()
        compose = z.read("docker-compose.ghcr.yml").decode()
        sync_section = compose[compose.index("sync-agent:") :]
        assert "metrics-buffer:/var/lib/powerblockade" in sync_section
        assert "metrics-buffer:" in compose[compose.index("volumes:") :]

    def test_zip_entry_modes(self) -> None:
        """ZIP entries must unpack with usable permissions for non-root users.

        dnsdist runs as 'pdns', sync-agent as uid 1000; restrictive default
        modes broke the bowlister v0.8.0 deploy (entrypoint + configs).
        """
        z = _make_zip()

        def mode(name: str) -> int:
            return (z.getinfo(name).external_attr >> 16) & 0o777

        assert mode("docker-entrypoint.sh") == 0o755
        assert mode(".env") == 0o600  # secrets: owner-only
        assert mode("config/recursor.conf.template") == 0o644  # placeholders only, no secrets
        assert mode("config/dnsdist.conf.template") == 0o644
        assert mode("config/forward-zones.conf") == 0o664
        assert mode("config/rpz.lua") == 0o644
        assert mode("rpz/") == 0o775  # sync-agent must be able to write RPZ files

    def test_compose_has_init_permissions(self) -> None:
        """Generated compose must bootstrap rpz/config ownership for uid 1000."""
        z = _make_zip()
        compose = z.read("docker-compose.ghcr.yml").decode()
        assert "init-permissions:" in compose
        assert "chown -R 1000:1000 /shared/rpz" in compose
        sync_section = compose[compose.index("sync-agent:") :]
        assert "init-permissions:" in sync_section
        assert "service_completed_successfully" in sync_section


class TestRecursorWebserverAuth:
    """Secondary packages must ship an authenticated recursor webserver.

    Release contract: the recursor webserver (metrics + API on :8082) is
    never passwordless. The package carries a per-package generated
    RECURSOR_WEB_PASSWORD in .env (mode 0600), passes it to the recursor
    and sync-agent services via env interpolation, and renders
    webserver-password into the conf at container start through the image
    entrypoint's ${RECURSOR_WEB_PASSWORD} substitution - the same
    mechanism the primary stack uses.
    """

    def test_env_contains_generated_web_password(self) -> None:
        z = _make_zip()
        value = _env_value(z.read(".env").decode(), "RECURSOR_WEB_PASSWORD")
        assert value, "RECURSOR_WEB_PASSWORD missing from generated .env"
        # Strong and entrypoint-safe: >= 32 chars from the charset the
        # recursor image entrypoint accepts ([A-Za-z0-9._~+=@-]).
        assert len(value) >= 32
        assert re.fullmatch(r"[A-Za-z0-9._~+=@-]+", value)

    def test_web_password_is_never_default_or_empty(self) -> None:
        z = _make_zip(recursor_api_key="")
        value = _env_value(z.read(".env").decode(), "RECURSOR_WEB_PASSWORD")
        assert value, "web password must exist even when the api key is unset"
        assert value not in {"change-me", "changeme", "password", "secret", "PowerBlockade"}

    def test_web_password_differs_per_package(self) -> None:
        v1 = _env_value(_make_zip().read(".env").decode(), "RECURSOR_WEB_PASSWORD")
        v2 = _env_value(_make_zip().read(".env").decode(), "RECURSOR_WEB_PASSWORD")
        assert v1 and v2
        assert v1 != v2, "each package must get its own generated password"

    def test_compose_passes_web_password_to_recursor(self) -> None:
        z = _make_zip()
        compose = z.read("docker-compose.ghcr.yml").decode()
        recursor_section = compose[compose.index("recursor:") :].split("recursor-reloader:")[0]
        assert "RECURSOR_WEB_PASSWORD: ${RECURSOR_WEB_PASSWORD:-}" in recursor_section

    def test_compose_passes_web_password_to_sync_agent(self) -> None:
        z = _make_zip()
        compose = z.read("docker-compose.ghcr.yml").decode()
        sync_section = compose[compose.index("sync-agent:") :]
        assert "RECURSOR_WEB_PASSWORD: ${RECURSOR_WEB_PASSWORD:-}" in sync_section

    def test_compose_body_never_embeds_generated_password(self) -> None:
        z = _make_zip()
        value = _env_value(z.read(".env").decode(), "RECURSOR_WEB_PASSWORD")
        compose = z.read("docker-compose.ghcr.yml").decode()
        assert value not in compose, "generated password must not leak into the compose file body"
        assert "${RECURSOR_WEB_PASSWORD" in compose

    def test_conf_template_templates_both_webserver_credentials(self) -> None:
        z = _make_zip()
        template = z.read("config/recursor.conf.template").decode()
        assert "webserver-password=${RECURSOR_WEB_PASSWORD}" in template
        assert "api-key=${RECURSOR_API_KEY}" in template
        # No literal secrets may sit in the template (it unpacks 0644).
        env = z.read(".env").decode()
        assert _env_value(env, "RECURSOR_WEB_PASSWORD") not in template
        assert _env_value(env, "RECURSOR_API_KEY") not in template

    def test_allow_from_narrowed_to_compose_network(self) -> None:
        z = _make_zip()
        template = z.read("config/recursor.conf.template").decode()
        # Primary posture: the compose network family only, never the world.
        assert "webserver-allow-from=172.30.0.0/16" in template
        assert "webserver-allow-from=0.0.0.0/0" not in template

    def test_recursor_mounts_conf_template(self) -> None:
        z = _make_zip()
        compose = z.read("docker-compose.ghcr.yml").decode()
        mount = "./config/recursor.conf.template:/etc/pdns-recursor/recursor.conf.template:ro"
        assert mount in compose
        # The static (rendered) conf mount is gone; the package ships no
        # "config/recursor.conf" entry at all.
        assert "./config/recursor.conf:" not in compose
        assert "config/recursor.conf" not in z.namelist()


class TestDnsdistExperimentConfig:
    """Generated secondaries carry the ratified E2/E4 dnsdist tuning.

    Previously the generator lagged the primary (useClientSubnet=true,
    staleTTL=60, setStaleCacheEntriesTTL(60), no keepStaleData); the
    reviewer asked for alignment. Reference: dnsdist/dnsdist.conf.template
    and docs/performance/experiment-log.md.
    """

    def test_e2_client_subnet_disabled(self) -> None:
        template = _make_zip().read("config/dnsdist.conf.template").decode()
        # Match the setting line only; comments may mention the rollback
        # value ("set useClientSubnet=true").
        assert re.search(r"^\s*useClientSubnet=false\s*$", template, re.MULTILINE)
        assert not re.search(r"^\s*useClientSubnet=true\s*$", template, re.MULTILINE)

    def test_e4_stale_ttl_300(self) -> None:
        template = _make_zip().read("config/dnsdist.conf.template").decode()
        assert "staleTTL=300" in template
        assert "staleTTL=60" not in template

    def test_e4_keep_stale_data(self) -> None:
        template = _make_zip().read("config/dnsdist.conf.template").decode()
        assert "keepStaleData=true" in template

    def test_e4_stale_cache_entries_ttl_300(self) -> None:
        template = _make_zip().read("config/dnsdist.conf.template").decode()
        assert "setStaleCacheEntriesTTL(300)" in template
        assert "setStaleCacheEntriesTTL(60)" not in template


class TestGeneratedComposeParses:
    """The generated compose file must parse as YAML and wire the auth env."""

    def test_compose_parses_and_wires_auth(self) -> None:
        z = _make_zip()
        doc = yaml.safe_load(z.read("docker-compose.ghcr.yml").decode())
        services = doc["services"]
        assert {
            "init-permissions",
            "dnsdist",
            "recursor",
            "recursor-reloader",
            "dnstap-processor",
            "sync-agent",
        } <= set(services)
        assert "RECURSOR_WEB_PASSWORD" in services["recursor"]["environment"]
        assert "RECURSOR_WEB_PASSWORD" in services["sync-agent"]["environment"]
        assert any(
            isinstance(v, str)
            and "recursor.conf.template:/etc/pdns-recursor/recursor.conf.template" in v
            for v in services["recursor"]["volumes"]
        )

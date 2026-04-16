"""Tests for node_generator secondary package output.

Verifies that generated ZIP packages use the official GHCR compose contract
with the unified recursor-reloader sidecar image and static-IP networking.
"""

from __future__ import annotations

import io
import zipfile

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
        assert "--profile secondary" in readme

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
        assert "config/recursor.conf" in names
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

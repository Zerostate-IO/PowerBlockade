"""Tests for node_generator secondary package output.

Verifies that generated ZIP packages use the official GHCR compose contract
with the unified recursor-reloader sidecar image.
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
        assert "config/dnsdist.conf" in names
        assert "config/rpz.lua" in names
        assert "config/forward-zones.conf" in names
        assert "rpz/.gitkeep" in names

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

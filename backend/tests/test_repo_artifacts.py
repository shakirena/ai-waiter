"""Статическая проверка артефактов репозитория: docker-compose (AC-7, #43), CI (AC-8, #44),
README (AC-9, #45), .gitignore и отсутствие IP-адресов (NFR-2). Без Docker и сети."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy" / "docker-compose.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
README = ROOT / "README.md"

pytestmark = pytest.mark.skipif(not COMPOSE.exists(), reason="тест запускается из полного клона репозитория")


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return _load(COMPOSE)


@pytest.fixture(scope="module")
def ci() -> dict[str, Any]:
    return _load(CI)


def _ci_commands(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


# ---------------------------------------------------------------- AC-7: docker compose


def test_compose_has_exactly_the_required_services(compose: dict[str, Any]) -> None:
    assert set(compose["services"]) == {"api", "worker", "postgres", "redis", "caddy"}


@pytest.mark.parametrize("service", ["api", "worker", "postgres", "redis", "caddy"])
def test_every_service_has_healthcheck(compose: dict[str, Any], service: str) -> None:
    check = compose["services"][service]["healthcheck"]
    assert check["test"]
    assert check["retries"] >= 1


def test_state_lives_in_named_volumes(compose: dict[str, Any]) -> None:
    assert {"pgdata", "media"} <= set(compose["volumes"])
    assert "pgdata:/var/lib/postgresql/data" in compose["services"]["postgres"]["volumes"]
    assert any(v.startswith("media:") for v in compose["services"]["api"]["volumes"])


def test_only_caddy_publishes_ports(compose: dict[str, Any]) -> None:
    published = {name for name, svc in compose["services"].items() if svc.get("ports")}
    assert published == {"caddy"}


def test_api_waits_for_storages_and_caddy_waits_for_api(compose: dict[str, Any]) -> None:
    depends = compose["services"]["api"]["depends_on"]
    assert depends["postgres"]["condition"] == "service_healthy"
    assert depends["redis"]["condition"] == "service_healthy"
    assert compose["services"]["caddy"]["depends_on"]["api"]["condition"] == "service_healthy"


def test_compose_forces_scaled_mode_and_requires_secrets(compose: dict[str, Any]) -> None:
    env = compose["x-app"]["environment"]
    assert env["APP_MODE"] == "scaled"
    assert env["REDIS_URL"] == "redis://redis:6379/0"
    # обязательные переменные: без значения compose не запускается (синтаксис ${ИМЯ:?...})
    text = COMPOSE.read_text(encoding="utf-8")
    for name in ("PUBLIC_DOMAIN", "POSTGRES_PASSWORD", "EDGE_SUBNET"):
        assert "${" + name + ":?" in text


def test_containers_forbid_privilege_escalation(compose: dict[str, Any]) -> None:
    assert "no-new-privileges:true" in compose["x-app"]["security_opt"]
    assert "no-new-privileges:true" in compose["services"]["caddy"]["security_opt"]


def test_dockerfile_runs_as_non_root_numeric_user() -> None:
    dockerfile = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"^USER\s+(\d+):(\d+)\s*$", dockerfile, re.MULTILINE)
    assert match is not None
    assert int(match.group(1)) > 0


# ---------------------------------------------------------------- AC-8: GitHub Actions


def test_ci_matrix_covers_linux_and_windows(ci: dict[str, Any]) -> None:
    for name in ("backend", "frontend"):
        job = ci["jobs"][name]
        assert set(job["strategy"]["matrix"]["os"]) == {"ubuntu-latest", "windows-latest"}
        assert job["strategy"]["fail-fast"] is False


def test_ci_backend_runs_ruff_and_pytest_on_python_312(ci: dict[str, Any]) -> None:
    job = ci["jobs"]["backend"]
    commands = _ci_commands(job)
    assert "ruff check" in commands
    assert "pytest" in commands
    uv_step = next(s for s in job["steps"] if "setup-uv" in s.get("uses", ""))
    assert uv_step["with"]["python-version"] == "3.12"
    assert uv_step["with"]["enable-cache"] is True


def test_ci_frontend_runs_install_lint_test_build_with_cache(ci: dict[str, Any]) -> None:
    job = ci["jobs"]["frontend"]
    commands = _ci_commands(job)
    for command in ("npm ci", "npm run lint", "npm run test", "npm run build"):
        assert command in commands
    node_step = next(s for s in job["steps"] if "setup-node" in s.get("uses", ""))
    assert node_step["with"]["cache"] == "npm"


def test_ci_has_services_job_for_db_and_scaled_markers(ci: dict[str, Any]) -> None:
    job = ci["jobs"]["backend-services"]
    assert set(job["services"]) == {"postgres", "redis"}
    assert 'pytest -q -m "db or scaled"' in _ci_commands(job)


def test_ci_does_not_swallow_failures(ci: dict[str, Any]) -> None:
    """Ни один шаг не использует continue-on-error: падение любого шага делает проверку красной."""
    for job in ci["jobs"].values():
        assert "continue-on-error" not in job
        assert all("continue-on-error" not in step for step in job["steps"])


def test_ci_token_is_read_only(ci: dict[str, Any]) -> None:
    assert ci["permissions"] == {"contents": "read"}


# ---------------------------------------------------------------- AC-9: README


def test_readme_commands_match_actual_frontend_scripts() -> None:
    scripts = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))["scripts"]
    readme = README.read_text(encoding="utf-8")
    used = set(re.findall(r"npm run ([a-z]+)", readme))
    assert {"lint", "typecheck", "test", "build", "dev"} <= used
    assert used <= set(scripts), f"в README есть скрипты, которых нет в package.json: {used - set(scripts)}"


def test_readme_has_required_sections_and_commands() -> None:
    readme = README.read_text(encoding="utf-8")
    assert "## Локальный запуск (режим single)" in readme
    assert "## Режим scaled (Docker Compose)" in readme
    assert "## Проверки" in readme
    for command in (
        "uv run python -m app",
        "uv run ruff check .",
        "uv run pytest -q",
        "docker compose -f deploy/docker-compose.yml up -d --build",
    ):
        assert command in readme


# ---------------------------------------------------------------- NFR-2: репозиторий публичный


def test_env_files_are_gitignored_except_example() -> None:
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in lines
    assert "!.env.example" in lines


@pytest.mark.parametrize("path", [COMPOSE, CI, ROOT / ".env.example", ROOT / "deploy" / "Caddyfile"])
def test_no_ip_addresses_or_keys_in_infrastructure_files(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    allowed = {"127.0.0.1", "0.0.0.0"}  # noqa: S104 — loopback и «все интерфейсы контейнера», не адреса заведения
    # Подсеть в нотации CIDR (пример EDGE_SUBNET в .env.example, закомментирован) — не адрес хоста.
    ips = set(re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b(?!/\d)", text)) - allowed
    assert ips == set(), f"{path.name}: найдены IP-адреса {ips}"
    assert "sk-ant-" not in text

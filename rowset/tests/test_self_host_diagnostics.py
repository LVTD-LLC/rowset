import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parents[2]
_DIAGNOSTICS_PATH = _REPO_ROOT / "deployment" / "self-host" / "diagnostics.py"
_PREFLIGHT = _REPO_ROOT / "deployment" / "self-host" / "preflight.sh"
_DOCTOR = _REPO_ROOT / "deployment" / "self-host" / "doctor.sh"
_CHECK_REQUIREMENTS = _REPO_ROOT / "deployment" / "self-host" / "check-requirements.py"
_REQUIREMENTS = _REPO_ROOT / "deployment" / "self-host" / "requirements.json"


def _load_diagnostics():
    spec = importlib.util.spec_from_file_location("self_host_diagnostics", _DIAGNOSTICS_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_diagnostics_parse_with_ubuntu_2404_python_grammar():
    ast.parse(
        _DIAGNOSTICS_PATH.read_text(), filename=str(_DIAGNOSTICS_PATH), feature_version=(3, 12)
    )


@pytest.mark.parametrize("command", ["preflight", "doctor"])
@pytest.mark.parametrize("status, expected_exit", [("PASS", 0), ("FAIL", 1)])
def test_diagnostic_cli_emits_ndjson_and_uses_failure_exit_contract(
    command, status, expected_exit, monkeypatch, capsys
):
    diagnostics = _load_diagnostics()
    result = ([diagnostics.Check("CONTRACT", status, "contract check")], [])
    monkeypatch.setattr(diagnostics, "run_preflight", lambda *_args: result)
    monkeypatch.setattr(diagnostics, "run_doctor", lambda *_args: result)
    monkeypatch.setattr(sys, "argv", ["diagnostics.py", command])

    with pytest.raises(SystemExit, match=str(expected_exit)):
        diagnostics.main()

    lines = capsys.readouterr().out.splitlines()
    assert [json.loads(line)["id"] for line in lines] == ["CONTRACT", "SUMMARY"]
    assert json.loads(lines[-1])["status"] == status


def test_requirement_checker_exposes_structured_failures_for_each_host_constraint():
    result = subprocess.run(
        [
            sys.executable,
            str(_CHECK_REQUIREMENTS),
            str(_REQUIREMENTS),
            "--platform",
            "linux/riscv64",
            "--os-id",
            "debian",
            "--os-version",
            "13",
            "--cpu-cores",
            "1",
            "--memory-bytes",
            "1000",
            "--disk-bytes",
            "1000",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert [check["id"] for check in payload["checks"]] == [
        "OS",
        "ARCH",
        "CPU",
        "MEMORY",
        "DISK",
    ]
    assert all(not check["passed"] for check in payload["checks"])
    assert payload["health_timeout_seconds"] == 180
    assert "1000" not in result.stderr


def test_renderer_emits_bounded_ndjson_without_secret_values():
    diagnostics = _load_diagnostics()
    secret = "secret-canary-value"
    checks = [
        diagnostics.Check("PREFLIGHT_ENV", "PASS", "configuration is valid"),
        diagnostics.Check(
            "PREFLIGHT_DNS",
            "FAIL",
            f"DNS does not point to this host ({secret})",
            "Point ROWSET_DOMAIN at a global address assigned to this host.",
        ),
    ]

    rendered = diagnostics.render(checks, secrets=[secret])
    lines = rendered.splitlines()

    assert len(lines) == 3
    assert [json.loads(line)["id"] for line in lines] == [
        "PREFLIGHT_ENV",
        "PREFLIGHT_DNS",
        "SUMMARY",
    ]
    assert json.loads(lines[-1]) == {
        "id": "SUMMARY",
        "status": "FAIL",
        "passed": 1,
        "failed": 1,
        "optional": 0,
    }
    assert secret not in rendered


def test_doctor_evaluates_every_service_returned_by_compose():
    diagnostics = _load_diagnostics()
    services = ["caddy", "db", "redis", "backend", "workers", "scheduler"]
    states = {
        service: {"Status": "running", "Health": {"Status": "healthy"}} for service in services
    }

    checks = diagnostics.service_checks(services, states)

    assert [check.id for check in checks] == [
        "DOCTOR_SERVICE_BACKEND",
        "DOCTOR_SERVICE_CADDY",
        "DOCTOR_SERVICE_DB",
        "DOCTOR_SERVICE_REDIS",
        "DOCTOR_SERVICE_SCHEDULER",
        "DOCTOR_SERVICE_WORKERS",
    ]
    assert all(check.status == "PASS" for check in checks)


def test_doctor_parses_compose_ndjson_service_states():
    diagnostics = _load_diagnostics()
    output = "\n".join(
        json.dumps({"Service": service, "State": "running", "Health": health})
        for service, health in (("caddy", "healthy"), ("workers", ""))
    )

    assert diagnostics.parse_compose_states(output) == {
        "caddy": {"Status": "running", "Health": {"Status": "healthy"}},
        "workers": {"Status": "running", "Health": {}},
    }


def test_doctor_fails_service_when_any_scaled_replica_is_unhealthy():
    diagnostics = _load_diagnostics()
    output = "\n".join(
        json.dumps(record)
        for record in (
            {"Service": "workers", "State": "exited", "Health": ""},
            {"Service": "workers", "State": "running", "Health": "healthy"},
        )
    )

    states = diagnostics.parse_compose_states(output)
    assert states["workers"]["Status"] == "degraded"
    assert diagnostics.service_checks(["workers"], states)[0].status == "FAIL"


def test_doctor_service_failure_has_one_stable_id_and_remediation():
    diagnostics = _load_diagnostics()

    checks = diagnostics.service_checks(
        ["backend", "workers"],
        {
            "backend": {"Status": "running", "Health": {"Status": "healthy"}},
            "workers": {"Status": "exited", "ExitCode": 1},
        },
    )

    assert checks[1] == diagnostics.Check(
        "DOCTOR_SERVICE_WORKERS",
        "FAIL",
        "service is exited",
        "Inspect bounded logs with: docker compose -p rowset logs --tail=100 workers",
    )


def test_optional_email_and_backup_capabilities_do_not_fail_doctor():
    diagnostics = _load_diagnostics()

    unconfigured = diagnostics.optional_capability_checks(
        {"MAILGUN_API_KEY": ""}, backup_timer_enabled=False, backup_timer_active=False
    )
    configured = diagnostics.optional_capability_checks(
        {"MAILGUN_API_KEY": "hidden"}, backup_timer_enabled=True, backup_timer_active=True
    )

    assert [(check.id, check.status) for check in unconfigured] == [
        ("DOCTOR_EMAIL", "OPTIONAL"),
        ("DOCTOR_BACKUP_TIMER", "OPTIONAL"),
    ]
    assert [(check.id, check.status) for check in configured] == [
        ("DOCTOR_EMAIL", "PASS"),
        ("DOCTOR_BACKUP_TIMER", "PASS"),
    ]
    assert "hidden" not in diagnostics.render(configured, secrets=["hidden"])


def test_configured_but_inactive_backup_timer_fails_doctor():
    diagnostics = _load_diagnostics()

    checks = diagnostics.optional_capability_checks(
        {"MAILGUN_API_KEY": ""}, backup_timer_enabled=True, backup_timer_active=False
    )

    assert checks[1].status == "FAIL"
    assert "systemctl" in checks[1].remediation


class _FakeRunner:
    def __init__(self, callback):
        self.callback = callback

    def run(self, command, *, env=None):
        return self.callback(command, env)


def test_doctor_happy_path_is_non_mutating_compact_and_machine_readable(tmp_path):
    diagnostics = _load_diagnostics()
    canary = "doctor-secret-canary"
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"ROWSET_DOMAIN=rowset.example.com\nMAILGUN_API_KEY=\nSECRET_KEY={canary}\n"
    )
    services = ["caddy", "db", "redis", "backend", "workers"]
    commands = []
    command_environments = []

    def respond(command, _environment):
        commands.append(command)
        command_environments.append((command, _environment))
        if command[0].endswith("validate-env.sh"):
            return diagnostics.CommandResult(0)
        if command[-2:] == ["config", "--services"]:
            return diagnostics.CommandResult(0, "\n".join(services) + "\n")
        if command[-4:] == ["ps", "--all", "--format", "json"]:
            return diagnostics.CommandResult(
                0,
                json.dumps(
                    [
                        {"Service": service, "State": "running", "Health": "healthy"}
                        for service in services
                    ]
                ),
            )
        if command[0] == "curl":
            healthy_root = command[-1].endswith("/") and "/mcp/" not in command[-1]
            return diagnostics.CommandResult(0, "200" if healthy_root else "401")
        if command[0] == "systemctl":
            return diagnostics.CommandResult(1)
        if "exec" in command:
            return diagnostics.CommandResult(0)
        raise AssertionError(f"unexpected doctor command: {command}")

    checks, secrets = diagnostics.run_doctor(_REPO_ROOT, env_file, _FakeRunner(respond))
    rendered = diagnostics.render(checks, secrets)

    assert all(check.status == "PASS" for check in checks[:-2])
    assert [check.status for check in checks[-2:]] == ["OPTIONAL", "OPTIONAL"]
    assert json.loads(rendered.splitlines()[-1])["status"] == "PASS"
    assert len(rendered.splitlines()) == len(checks) + 1
    assert canary not in rendered
    assert len(commands) == 11
    assert sum(command[-4:] == ["ps", "--all", "--format", "json"] for command in commands) == 1
    compose_environments = [
        environment
        for command, environment in command_environments
        if command[0:2] == ["docker", "compose"]
    ]
    assert compose_environments
    assert all(
        environment["ROWSET_ENV_FILE"] == str(env_file) for environment in compose_environments
    )


def test_preflight_broken_host_reports_stable_failures_without_command_output(
    tmp_path, monkeypatch
):
    diagnostics = _load_diagnostics()
    canary = "preflight-secret-canary"
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ROWSET_IMAGE=ghcr.io/lvtd-llc/rowset:2026.07.16-0\n"
        "ROWSET_DOMAIN=wrong.example.com\n"
        f"SECRET_KEY={canary}\n"
    )
    monkeypatch.setattr(
        diagnostics,
        "_requirement_checks",
        lambda _root, _runner: [diagnostics.Check("PREFLIGHT_OS", "PASS", "supported")],
    )

    def respond(command, _environment):
        if command[0] == "getent":
            return diagnostics.CommandResult(0, "203.0.113.20 STREAM wrong.example.com\n")
        if command[0] == "ip":
            return diagnostics.CommandResult(0, "2: eth0 inet 203.0.113.21/24 scope global eth0\n")
        if command[0] == "ss":
            return diagnostics.CommandResult(0, "LISTEN 0 4096 0.0.0.0:80 0.0.0.0:*\n")
        if command[:2] == ["docker", "version"]:
            return diagnostics.CommandResult(1)
        if command[:3] == ["docker", "compose", "version"]:
            return diagnostics.CommandResult(0)
        if command[:3] == ["docker", "buildx", "imagetools"]:
            return diagnostics.CommandResult(1)
        return diagnostics.CommandResult(0)

    checks, secrets = diagnostics.run_preflight(_REPO_ROOT, env_file, _FakeRunner(respond))
    failures = [check.id for check in checks if check.status == "FAIL"]
    rendered = diagnostics.render(checks, secrets)

    assert failures == [
        "PREFLIGHT_DNS",
        "PREFLIGHT_PORT_80",
        "PREFLIGHT_DOCKER",
        "PREFLIGHT_REGISTRY",
    ]
    assert canary not in rendered
    assert json.loads(rendered.splitlines()[-1])["status"] == "FAIL"


def test_preflight_distinguishes_missing_buildx_from_registry_failure(tmp_path, monkeypatch):
    diagnostics = _load_diagnostics()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ROWSET_IMAGE=ghcr.io/example/rowset:latest\nROWSET_DOMAIN=rowset.example.com\n"
    )
    monkeypatch.setattr(diagnostics, "_requirement_checks", lambda *_args: [])
    inspected_manifest = False

    def respond(command, _environment):
        nonlocal inspected_manifest
        if command[:3] == ["docker", "buildx", "version"]:
            return diagnostics.CommandResult(1)
        if command[:3] == ["docker", "buildx", "imagetools"]:
            inspected_manifest = True
        return diagnostics.CommandResult(0)

    checks, _secrets = diagnostics.run_preflight(_REPO_ROOT, env_file, _FakeRunner(respond))

    assert next(check for check in checks if check.id == "PREFLIGHT_BUILDX").status == "FAIL"
    assert all(check.id != "PREFLIGHT_REGISTRY" for check in checks)
    assert not inspected_manifest


def test_diagnostic_entrypoints_are_read_only_and_use_the_shared_runner():
    diagnostics = _DIAGNOSTICS_PATH.read_text()
    preflight = _PREFLIGHT.read_text()
    doctor = _DOCTOR.read_text()

    assert 'diagnostics.py" preflight' in preflight
    assert 'diagnostics.py" doctor' in doctor
    for forbidden in (
        "post_deploy_smoke_test",
        "createsuperuser",
        "create_agent_api_key",
        "docker compose up",
        "docker compose down",
        "manage.py migrate --noinput",
    ):
        assert forbidden not in diagnostics


def test_self_hosting_docs_make_preflight_and_doctor_the_supported_gate():
    self_hosting = (_REPO_ROOT / "SELF_HOSTING.md").read_text()

    assert "deployment/self-host/preflight.sh" in self_hosting
    assert "deployment/self-host/doctor.sh" in self_hosting
    assert "continue until doctor reports a passing summary" in self_hosting
    assert "authenticated smoke test" in self_hosting

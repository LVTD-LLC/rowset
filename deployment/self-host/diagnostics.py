#!/usr/bin/env python3
import argparse
import ipaddress
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Check:
    id: str
    status: str
    detail: str
    remediation: str = ""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""


class CommandRunner:
    def run(self, command: list[str], *, env: dict[str, str] | None = None) -> CommandResult:
        try:
            result = subprocess.run(
                command,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except OSError:
            return CommandResult(1)
        except subprocess.TimeoutExpired:
            return CommandResult(1)
        return CommandResult(result.returncode, result.stdout[:20_000])


def _redact(value: str, secrets: list[str]) -> str:
    for secret in sorted((secret for secret in secrets if secret), key=len, reverse=True):
        value = value.replace(secret, "[REDACTED]")
    return value


def render(checks: list[Check], secrets: list[str]) -> str:
    lines = []
    for check in checks:
        payload = asdict(check)
        payload["detail"] = _redact(payload["detail"], secrets)
        payload["remediation"] = _redact(payload["remediation"], secrets)
        if not payload["remediation"]:
            payload.pop("remediation")
        lines.append(json.dumps(payload, separators=(",", ":"), sort_keys=False))
    summary = {
        "id": "SUMMARY",
        "status": "FAIL" if any(check.status == "FAIL" for check in checks) else "PASS",
        "passed": sum(check.status == "PASS" for check in checks),
        "failed": sum(check.status == "FAIL" for check in checks),
        "optional": sum(check.status == "OPTIONAL" for check in checks),
    }
    lines.append(json.dumps(summary, separators=(",", ":"), sort_keys=False))
    return "\n".join(lines) + "\n"


def _load_environment(path: Path) -> dict[str, str]:
    values = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return values
    for line in lines:
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            values[key] = value
    return values


def _secrets(values: dict[str, str]) -> list[str]:
    secret_markers = ("KEY", "PASSWORD", "SECRET", "TOKEN", "DSN")
    return [
        value for key, value in values.items() if value and any(x in key for x in secret_markers)
    ]


def _pass(check_id: str, detail: str) -> Check:
    return Check(check_id, "PASS", detail)


def _fail(check_id: str, detail: str, remediation: str) -> Check:
    return Check(check_id, "FAIL", detail, remediation)


def service_checks(services: list[str], states: dict[str, dict]) -> list[Check]:
    checks = []
    for service in sorted(set(services)):
        check_id = "DOCTOR_SERVICE_" + re.sub(r"[^A-Z0-9]+", "_", service.upper()).strip("_")
        state = states.get(service, {})
        status = state.get("Status", "missing")
        health = state.get("Health", {}).get("Status")
        if status == "running" and health in (None, "healthy"):
            detail = "service is running" if health is None else "service is running and healthy"
            checks.append(_pass(check_id, detail))
        else:
            detail = f"service is {status}"
            if status == "running" and health:
                detail = f"service health is {health}"
            checks.append(
                _fail(
                    check_id,
                    detail,
                    "Inspect bounded logs with: "
                    f"docker compose -p rowset logs --tail=100 {service}",
                )
            )
    return checks


def optional_capability_checks(
    environment: dict[str, str], *, backup_timer_enabled: bool, backup_timer_active: bool
) -> list[Check]:
    email = (
        _pass("DOCTOR_EMAIL", "email delivery is configured")
        if environment.get("MAILGUN_API_KEY")
        else Check("DOCTOR_EMAIL", "OPTIONAL", "email delivery is not configured")
    )
    if not backup_timer_enabled:
        backup = Check("DOCTOR_BACKUP_TIMER", "OPTIONAL", "backup timer is not enabled")
    elif backup_timer_active:
        backup = _pass("DOCTOR_BACKUP_TIMER", "backup timer is enabled and active")
    else:
        backup = _fail(
            "DOCTOR_BACKUP_TIMER",
            "backup timer is enabled but inactive",
            "Inspect bounded status with: systemctl status --no-pager -n 50 rowset-backup.timer",
        )
    return [email, backup]


def _os_release(path: Path = Path("/etc/os-release")) -> tuple[str, str]:
    values = _load_environment(path)
    return values.get("ID", "unknown").strip('"'), values.get("VERSION_ID", "unknown").strip('"')


def _host_platform() -> str:
    machine = platform.machine().lower()
    architecture = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(
        machine, machine
    )
    return f"linux/{architecture}"


def _memory_bytes(path: Path = Path("/proc/meminfo")) -> int:
    try:
        match = re.search(r"^MemTotal:\s+(\d+)\s+kB$", path.read_text(), re.MULTILINE)
    except OSError:
        return 0
    return int(match.group(1)) * 1024 if match else 0


def _requirement_checks(root: Path, runner: CommandRunner) -> list[Check]:
    os_id, os_version = _os_release()
    command = [
        sys.executable,
        str(root / "deployment/self-host/check-requirements.py"),
        str(root / "deployment/self-host/requirements.json"),
        "--platform",
        _host_platform(),
        "--os-id",
        os_id,
        "--os-version",
        os_version,
        "--cpu-cores",
        str(os.cpu_count() or 0),
        "--memory-bytes",
        str(_memory_bytes()),
        "--disk-bytes",
        str(shutil.disk_usage(root).free),
        "--json",
    ]
    result = runner.run(command)
    try:
        outcomes = json.loads(result.stdout)["checks"]
    except json.JSONDecodeError:
        outcomes = None
    except KeyError:
        outcomes = None
    except TypeError:
        outcomes = None
    if outcomes is None:
        return [
            _fail(
                "PREFLIGHT_REQUIREMENTS",
                "host requirements could not be evaluated",
                "Restore deployment/self-host/requirements.json and check-requirements.py.",
            )
        ]
    definitions = {
        "OS": ("operating system is supported", "Use a supported Ubuntu release."),
        "ARCH": (
            "architecture is supported",
            "Use a supported linux/amd64 or linux/arm64 host.",
        ),
        "CPU": (
            "CPU meets the minimum",
            "Resize the host to the published minimum CPU profile.",
        ),
        "MEMORY": (
            "memory meets the minimum",
            "Resize the host to the published minimum RAM profile.",
        ),
        "DISK": (
            "disk space meets the minimum",
            "Free disk space or resize to the published minimum disk profile.",
        ),
    }
    checks = []
    for outcome in outcomes:
        check_id = outcome["id"]
        pass_detail, remediation = definitions.get(
            check_id,
            (f"requirement {check_id} is satisfied", "Meet the published host requirement."),
        )
        checks.append(
            _pass(f"PREFLIGHT_{check_id}", pass_detail)
            if outcome["passed"]
            else _fail(
                f"PREFLIGHT_{check_id}",
                f"requirement {check_id} is not satisfied",
                remediation,
            )
        )
    return checks


def _dns_check(domain: str, runner: CommandRunner) -> Check:
    dns = runner.run(["getent", "ahosts", domain])
    local = runner.run(["ip", "-o", "addr", "show", "scope", "global"])
    dns_addresses = {line.split()[0] for line in dns.stdout.splitlines() if line.split()}
    local_addresses = set(re.findall(r"\binet6?\s+([^/\s]+)", local.stdout))
    try:
        dns_addresses = {str(ipaddress.ip_address(value)) for value in dns_addresses}
        local_addresses = {str(ipaddress.ip_address(value)) for value in local_addresses}
    except ValueError:
        return _fail(
            "PREFLIGHT_DNS",
            "DNS or host addresses could not be parsed",
            "Confirm ROWSET_DOMAIN resolves to an address assigned to this host.",
        )
    if dns.returncode == 0 and local.returncode == 0 and dns_addresses & local_addresses:
        return _pass("PREFLIGHT_DNS", "domain resolves to this host")
    return _fail(
        "PREFLIGHT_DNS",
        "domain does not resolve to this host",
        "Point ROWSET_DOMAIN at a global address assigned to this host.",
    )


def _port_checks(runner: CommandRunner) -> list[Check]:
    result = runner.run(["ss", "-H", "-ltn"])
    if result.returncode != 0:
        return [
            _fail(
                f"PREFLIGHT_PORT_{port}",
                "listening ports could not be inspected",
                "Install iproute2 and rerun preflight.",
            )
            for port in (80, 443)
        ]
    listening = set(re.findall(r"(?:^|[\[\]:.])(80|443)(?:\s|$)", result.stdout, re.MULTILINE))
    return [
        _fail(
            f"PREFLIGHT_PORT_{port}",
            f"TCP port {port} is already in use",
            f"Stop the listener on TCP {port}, or use an existing ingress "
            "instead of bundled Caddy.",
        )
        if str(port) in listening
        else _pass(f"PREFLIGHT_PORT_{port}", f"TCP port {port} is available")
        for port in (80, 443)
    ]


def _registry_check(root: Path, image: str, host_platform: str, runner: CommandRunner) -> Check:
    with tempfile.TemporaryDirectory(prefix="rowset-preflight-") as docker_config:
        Path(docker_config, "config.json").write_text('{"auths":{}}\n')
        environment = {**os.environ, "DOCKER_CONFIG": docker_config}
        result = runner.run(["docker", "buildx", "imagetools", "inspect", image], env=environment)
        manifest_file = Path(docker_config, "manifest.txt")
        manifest_file.write_text(result.stdout)
        platform_result = runner.run(
            [
                str(root / "deployment/verify-image-platforms.sh"),
                "--manifest-file",
                str(manifest_file),
                image,
                host_platform,
            ]
        )
    if result.returncode == 0 and platform_result.returncode == 0:
        return _pass(
            "PREFLIGHT_REGISTRY", "release manifest is anonymously available for this host"
        )
    return _fail(
        "PREFLIGHT_REGISTRY",
        "release manifest is not anonymously available for this host",
        "Use a published Rowset release whose manifest includes this host architecture.",
    )


def run_preflight(
    root: Path, env_file: Path, runner: CommandRunner
) -> tuple[list[Check], list[str]]:
    environment = _load_environment(env_file)
    secrets = _secrets(environment)
    checks = []
    validation = runner.run([str(root / "deployment/self-host/validate-env.sh"), str(env_file)])
    checks.append(
        _pass("PREFLIGHT_ENV", "production environment is valid")
        if validation.returncode == 0
        else _fail(
            "PREFLIGHT_ENV",
            "production environment is invalid",
            "Run deployment/self-host/validate-env.sh and correct the named setting.",
        )
    )
    required = [
        root / "docker-compose-prod.yml",
        root / "deployment/self-host/requirements.json",
        root / "deployment/self-host/check-requirements.py",
        root / "deployment/self-host/validate-env.sh",
        env_file,
    ]
    checks.append(
        _pass("PREFLIGHT_FILES", "required deployment files are readable")
        if all(path.is_file() and os.access(path, os.R_OK) for path in required)
        else _fail(
            "PREFLIGHT_FILES",
            "required deployment files are missing or unreadable",
            "Restore the complete release bundle and make its files readable by the invoking user.",
        )
    )
    checks.extend(_requirement_checks(root, runner))
    checks.append(_dns_check(environment.get("ROWSET_DOMAIN", ""), runner))
    checks.extend(_port_checks(runner))
    checks.append(
        _pass("PREFLIGHT_DOCKER", "Docker Engine is available")
        if runner.run(["docker", "version"]).returncode == 0
        else _fail(
            "PREFLIGHT_DOCKER", "Docker Engine is unavailable", "Install and start Docker Engine."
        )
    )
    checks.append(
        _pass("PREFLIGHT_COMPOSE", "Docker Compose v2 is available")
        if runner.run(["docker", "compose", "version"]).returncode == 0
        else _fail(
            "PREFLIGHT_COMPOSE",
            "Docker Compose v2 is unavailable",
            "Install the Docker Compose v2 plugin.",
        )
    )
    buildx_available = runner.run(["docker", "buildx", "version"]).returncode == 0
    checks.append(
        _pass("PREFLIGHT_BUILDX", "Docker Buildx is available")
        if buildx_available
        else _fail(
            "PREFLIGHT_BUILDX",
            "Docker Buildx is unavailable",
            "Install the Docker Buildx plugin.",
        )
    )
    if buildx_available:
        checks.append(
            _registry_check(
                root,
                environment.get("ROWSET_IMAGE", ""),
                _host_platform(),
                runner,
            )
        )
    return checks, secrets


def _compose_base(root: Path, env_file: Path) -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        str(root / "docker-compose-prod.yml"),
        "-p",
        "rowset",
    ]


def _http_status(runner: CommandRunner, url: str, *, mcp: bool = False) -> int:
    command = ["curl", "-sS", "--max-time", "10", "-o", "/dev/null", "-w", "%{http_code}"]
    if mcp:
        command.extend(
            [
                "-X",
                "POST",
                "-H",
                "Content-Type: application/json",
                "-H",
                "Accept: application/json, text/event-stream",
                "--data",
                '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}',
            ]
        )
    result = runner.run([*command, url])
    try:
        return int(result.stdout.strip()) if result.returncode == 0 else 0
    except ValueError:
        return 0


def parse_compose_states(output: str) -> dict[str, dict]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        try:
            payload = [json.loads(line) for line in output.splitlines() if line.strip()]
        except json.JSONDecodeError:
            return {}
    if isinstance(payload, dict):
        payload = [payload]
    try:
        records: dict[str, list[dict]] = {}
        for item in payload:
            records.setdefault(item["Service"], []).append(item)
        states = {}
        for service, replicas in records.items():
            if all(
                replica.get("State") == "running" and replica.get("Health") in (None, "", "healthy")
                for replica in replicas
            ):
                all_healthchecked = all(replica.get("Health") == "healthy" for replica in replicas)
                states[service] = {
                    "Status": "running",
                    "Health": {"Status": "healthy"} if all_healthchecked else {},
                }
            else:
                states[service] = {"Status": "degraded", "Health": {}}
        return states
    except KeyError:
        return {}
    except TypeError:
        return {}


def run_doctor(root: Path, env_file: Path, runner: CommandRunner) -> tuple[list[Check], list[str]]:
    environment = _load_environment(env_file)
    secrets = _secrets(environment)
    checks = []
    validation = runner.run([str(root / "deployment/self-host/validate-env.sh"), str(env_file)])
    checks.append(
        _pass("DOCTOR_ENV", "production environment is valid")
        if validation.returncode == 0
        else _fail(
            "DOCTOR_ENV",
            "production environment is invalid",
            "Correct the environment before diagnosing services.",
        )
    )
    compose = _compose_base(root, env_file)
    compose_environment = {**os.environ, "ROWSET_ENV_FILE": str(env_file)}
    configured = runner.run([*compose, "config", "--services"], env=compose_environment)
    services = sorted(set(configured.stdout.split())) if configured.returncode == 0 else []
    checks.append(
        _pass("DOCTOR_COMPOSE", "production Compose configuration is valid")
        if services
        else _fail(
            "DOCTOR_COMPOSE",
            "production Compose configuration is invalid",
            "Render docker-compose-prod.yml with the validated environment and correct the "
            "reported configuration.",
        )
    )
    status_result = runner.run(
        [*compose, "ps", "--all", "--format", "json"], env=compose_environment
    )
    states = parse_compose_states(status_result.stdout) if status_result.returncode == 0 else {}
    checks.extend(service_checks(services, states))
    command_checks = (
        (
            "DOCTOR_POSTGRES",
            [*compose, "exec", "-T", "db", "sh", "-c", 'pg_isready -U "$POSTGRES_USER"'],
            "PostgreSQL accepts connections",
            "PostgreSQL does not accept connections",
            "Inspect bounded db logs and verify PostgreSQL health.",
        ),
        (
            "DOCTOR_REDIS",
            [
                *compose,
                "exec",
                "-T",
                "redis",
                "sh",
                "-c",
                'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli ping',
            ],
            "Redis accepts authenticated commands",
            "Redis does not accept authenticated commands",
            "Inspect bounded redis logs and verify REDIS_PASSWORD.",
        ),
        (
            "DOCTOR_MIGRATIONS",
            [*compose, "exec", "-T", "backend", "python", "manage.py", "migrate", "--check"],
            "database migrations are current",
            "database migrations are not current",
            "Apply the release migration command, then rerun doctor.",
        ),
    )
    for check_id, command, pass_detail, fail_detail, remediation in command_checks:
        checks.append(
            _pass(check_id, pass_detail)
            if runner.run(command, env=compose_environment).returncode == 0
            else _fail(check_id, fail_detail, remediation)
        )
    domain = environment.get("ROWSET_DOMAIN", "")
    https_status = _http_status(runner, f"https://{domain}/")
    checks.append(
        _pass("DOCTOR_HTTPS", "trusted HTTPS is serving Rowset")
        if 200 <= https_status < 400
        else _fail(
            "DOCTOR_HTTPS",
            "trusted HTTPS is not serving Rowset",
            "Confirm DNS and ports 80/443, then inspect bounded Caddy logs.",
        )
    )
    rest_status = _http_status(runner, f"https://{domain}/api/user")
    checks.append(
        _pass("DOCTOR_REST_AUTH", "unauthenticated REST access is rejected")
        if rest_status == 401
        else _fail(
            "DOCTOR_REST_AUTH",
            "unauthenticated REST access is not rejected with 401",
            "Verify production authentication and proxy routing for /api/user.",
        )
    )
    mcp_status = _http_status(runner, f"https://{domain}/mcp/", mcp=True)
    checks.append(
        _pass("DOCTOR_MCP_AUTH", "unauthenticated MCP access is rejected")
        if mcp_status == 401
        else _fail(
            "DOCTOR_MCP_AUTH",
            "unauthenticated MCP access is not rejected with 401",
            "Verify production bearer authentication and proxy routing for /mcp/.",
        )
    )
    timer_enabled = (
        runner.run(["systemctl", "is-enabled", "--quiet", "rowset-backup.timer"]).returncode == 0
    )
    timer_active = (
        runner.run(["systemctl", "is-active", "--quiet", "rowset-backup.timer"]).returncode == 0
    )
    checks.extend(
        optional_capability_checks(
            environment,
            backup_timer_enabled=timer_enabled,
            backup_timer_active=timer_active,
        )
    )
    return checks, secrets


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "doctor"))
    parser.add_argument("environment_file", nargs="?", type=Path, default=root / ".env")
    args = parser.parse_args()
    env_file = args.environment_file.expanduser().resolve()
    runner = CommandRunner()
    if args.command == "preflight":
        checks, secrets = run_preflight(root, env_file, runner)
    else:
        checks, secrets = run_doctor(root, env_file, runner)
    sys.stdout.write(render(checks, secrets))
    raise SystemExit(1 if any(check.status == "FAIL" for check in checks) else 0)


if __name__ == "__main__":
    main()

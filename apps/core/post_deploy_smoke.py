import json
from collections.abc import Callable, Iterable
from math import ceil
from time import monotonic, sleep
from urllib.parse import urlsplit
from uuid import uuid4

import requests
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test.utils import override_settings
from django.utils import timezone
from django_q.brokers import get_broker
from django_q.models import Task
from django_q.signing import SignedPackage

from apps.core.choices import AgentApiKeyAccessLevel, ProfileStates
from apps.core.models import Profile
from apps.core.post_deploy_smoke_auth import SMOKE_HEADER, create_smoke_token
from apps.core.services import create_agent_api_key

MCP_PROTOCOL_VERSION = "2025-03-26"
SMOKE_STAGES = (
    "setup",
    "rest_auth",
    "mcp_initialize",
    "mcp_tools",
    "dataset_create",
    "dataset_read",
    "worker",
)
REQUIRED_MCP_TOOLS = ("get_user_info", "list_dataset_rows")
WORKER_RESULT_TTL = 300


class SmokeTestError(RuntimeError):
    pass


def validate_smoke_base_url(base_url: str, configured_site_url: str) -> None:
    target = urlsplit(base_url)
    configured = urlsplit(configured_site_url)
    if (
        target.scheme not in {"http", "https"}
        or not target.hostname
        or target.username
        or target.password
        or target.query
        or target.fragment
        or target.path not in {"", "/"}
    ):
        raise ValueError("Smoke base URL must be a plain HTTP(S) origin without credentials.")

    if target.hostname in {"127.0.0.1", "::1", "localhost", "backend"}:
        return

    target_origin = (target.scheme, target.hostname, target.port)
    configured_origin = (configured.scheme, configured.hostname, configured.port)
    if target.scheme != "https" or target_origin != configured_origin:
        raise ValueError("Smoke base URL must match the configured HTTPS SITE_URL origin.")


class PostDeploySmokeClient:
    def __init__(self, base_url: str, raw_key: str, timeout: float, smoke_token: str):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {raw_key}",
                "Accept": "application/json, text/event-stream",
                SMOKE_HEADER: smoke_token,
            }
        )
        self._request_id = 0

    def close(self) -> None:
        self.session.close()

    def _request(self, method: str, path: str, *, label: str, **kwargs) -> requests.Response:
        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                timeout=self.timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise SmokeTestError(f"{label} request failed ({type(exc).__name__}).") from None

        if not 200 <= response.status_code < 300:
            raise SmokeTestError(f"{label} returned unexpected HTTP {response.status_code}.")
        return response

    @staticmethod
    def _json(response: requests.Response, label: str) -> dict:
        try:
            payload = response.json()
        except requests.JSONDecodeError:
            raise SmokeTestError(f"{label} returned invalid JSON.") from None
        if not isinstance(payload, dict):
            raise SmokeTestError(f"{label} returned an unexpected JSON value.")
        return payload

    def _mcp_call(self, method: str, params: dict | None = None) -> dict:
        self._request_id += 1
        body = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
        }
        if params is not None:
            body["params"] = params
        response = self._request("POST", "/mcp/", label=f"MCP {method}", json=body)
        payload = self._json(response, f"MCP {method}")
        if "error" in payload or not isinstance(payload.get("result"), dict):
            raise SmokeTestError(f"MCP {method} returned a JSON-RPC error.")
        return payload["result"]

    def verify_rest_auth(self, expected_email: str) -> None:
        response = self._request("GET", "/api/user", label="REST authentication")
        payload = self._json(response, "REST authentication")
        if payload.get("email") != expected_email:
            raise SmokeTestError("REST authentication returned the wrong temporary user.")

    def initialize_mcp(self) -> None:
        result_payload = self._mcp_call(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "rowset-post-deploy-smoke", "version": "1"},
            },
        )
        if result_payload.get("serverInfo", {}).get("name") != "Rowset":
            raise SmokeTestError("MCP initialize returned an unexpected server identity.")

    def list_mcp_tools(self, required_tools: Iterable[str]) -> None:
        result_payload = self._mcp_call("tools/list")
        tools = result_payload.get("tools")
        if not isinstance(tools, list):
            raise SmokeTestError("MCP tools/list returned an invalid tool list.")
        names = {tool.get("name") for tool in tools if isinstance(tool, dict)}
        missing = sorted(set(required_tools) - names)
        if missing:
            raise SmokeTestError(f"MCP tools/list is missing required tools: {', '.join(missing)}.")

    def create_dataset(self, name: str, marker: str) -> str:
        response = self._request(
            "POST",
            "/api/datasets",
            label="REST dataset creation",
            json={
                "name": name,
                "headers": ["smoke_id", "value"],
                "index_column": "smoke_id",
                "rows": [{"smoke_id": marker, "value": "ready"}],
                "metadata": {"system": {"kind": "post_deploy_smoke", "marker": marker}},
            },
        )
        if response.status_code != 201:
            raise SmokeTestError(
                f"REST dataset creation returned unexpected HTTP {response.status_code}."
            )
        payload = self._json(response, "REST dataset creation")
        dataset_key = payload.get("dataset", {}).get("key")
        if not dataset_key:
            raise SmokeTestError("REST dataset creation did not return a dataset key.")
        return str(dataset_key)

    def read_dataset_row(self, dataset_key: str, marker: str) -> None:
        result_payload = self._mcp_call(
            "tools/call",
            {
                "name": "list_dataset_rows",
                "arguments": {"dataset_key": dataset_key, "limit": 10},
            },
        )
        if result_payload.get("isError") is True:
            raise SmokeTestError("MCP list_dataset_rows returned a tool error.")
        structured = result_payload.get("structuredContent")
        if not isinstance(structured, dict):
            content = result_payload.get("content") or []
            try:
                structured = json.loads(content[0]["text"])
            except IndexError, KeyError, TypeError, json.JSONDecodeError:
                raise SmokeTestError("MCP list_dataset_rows returned invalid row data.") from None
        rows = structured.get("rows")
        if not isinstance(rows, list) or not any(
            isinstance(row, dict) and row.get("data", {}).get("smoke_id") == marker for row in rows
        ):
            raise SmokeTestError("MCP list_dataset_rows did not return the temporary row.")


class WorkerReadinessProbe:
    def __init__(self, broker=None):
        self.broker = broker or get_broker()
        self.keys: tuple[str, str] | None = None
        self.task_id: str | None = None
        self.queue_package: str | None = None

    def verify(self, marker: str, timeout: float) -> None:
        active_key = f"rowset:post-deploy-smoke:{marker}:active"
        result_key = f"rowset:post-deploy-smoke:{marker}:result"
        self.keys = (active_key, result_key)
        ttl = ceil(timeout) + 60
        self.broker.connection.set(active_key, marker, ex=ttl)
        self.task_id = uuid4().hex
        self.queue_package = SignedPackage.dumps(
            {
                "id": self.task_id,
                "name": f"post-deploy-smoke-{marker}",
                "func": "apps.core.post_deploy_smoke.worker_readiness_task",
                "args": (marker,),
                "kwargs": {},
                "started": timezone.now(),
                "save": False,
            }
        )
        self.broker.enqueue(self.queue_package)
        deadline = monotonic() + timeout
        while True:
            worker_result = self.broker.connection.get(result_key)
            if worker_result in (marker, marker.encode()):
                return
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise SmokeTestError("Worker readiness task did not complete before the timeout.")
            sleep(min(0.1, remaining))

    def cleanup(self) -> None:
        cleanup_errors = []
        if self.queue_package:
            try:
                self.broker.connection.lrem(self.broker.list_key, 1, self.queue_package)
            except Exception as exc:
                cleanup_errors.append(exc)
        if self.task_id:
            try:
                Task.objects.filter(id=self.task_id).delete()
            except Exception as exc:
                cleanup_errors.append(exc)
        if self.keys:
            try:
                self.broker.connection.delete(*self.keys)
            except Exception as exc:
                cleanup_errors.append(exc)
        if cleanup_errors:
            raise SmokeTestError("Worker readiness cleanup failed.")


def worker_readiness_task(marker: str) -> None:
    """Atomically publish readiness only while the command's probe is still active."""
    active_key = f"rowset:post-deploy-smoke:{marker}:active"
    result_key = f"rowset:post-deploy-smoke:{marker}:result"
    try:
        get_broker().connection.eval(
            """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                redis.call('set', KEYS[2], ARGV[1], 'EX', ARGV[2])
                return 1
            end
            return 0
            """,
            2,
            active_key,
            result_key,
            marker,
            WORKER_RESULT_TTL,
        )
    except Exception:
        # A failed Django-Q task is persisted even with save=False. Let the command's
        # readiness timeout report the failure without leaving a durable task row.
        return


class PostDeploySmokeRunner:
    def __init__(
        self,
        *,
        base_url: str,
        timeout: float,
        fail_after: str | None = None,
        client_factory: Callable[..., PostDeploySmokeClient] = PostDeploySmokeClient,
        worker_probe: WorkerReadinessProbe | None = None,
        report: Callable[[str], None] | None = None,
    ):
        if fail_after is not None and fail_after not in SMOKE_STAGES:
            raise ValueError(f"Unknown smoke stage: {fail_after}")
        self.base_url = base_url
        self.timeout = timeout
        self.fail_after = fail_after
        self.client_factory = client_factory
        self.worker_probe = worker_probe or WorkerReadinessProbe()
        self.report = report or (lambda _message: None)

    def _complete_stage(self, stage: str, message: str) -> None:
        self.report(f"ok: {message}")
        if self.fail_after == stage:
            raise SmokeTestError(f"Forced failure after {stage}")

    @staticmethod
    def _create_temporary_identity(marker: str):
        username = f"rowset-smoke-{marker}"
        email = f"{username}@invalid.example"
        user_model = get_user_model()
        with transaction.atomic():
            user = user_model(username=username, email=email, is_active=True)
            user_model.objects.bulk_create([user])
            profile = Profile.objects.create(
                user=user,
                state=ProfileStates.SUBSCRIBED,
            )
            with override_settings(POSTHOG_API_KEY=""):
                credential = create_agent_api_key(
                    profile,
                    f"Post-deploy smoke {marker}",
                    AgentApiKeyAccessLevel.READ_WRITE,
                )
        return user, credential.raw_key

    def run(self) -> None:
        marker = uuid4().hex
        user = None
        client = None
        completed = False
        try:
            user, raw_key = self._create_temporary_identity(marker)
            self._complete_stage("setup", "temporary credentials created")

            smoke_token = create_smoke_token(marker)
            client = self.client_factory(self.base_url, raw_key, self.timeout, smoke_token)
            client.verify_rest_auth(user.email)
            self._complete_stage("rest_auth", "REST authentication")

            client.initialize_mcp()
            self._complete_stage("mcp_initialize", "MCP initialize")

            client.list_mcp_tools(REQUIRED_MCP_TOOLS)
            self._complete_stage("mcp_tools", "MCP tool discovery")

            dataset_key = client.create_dataset(f"Post-deploy smoke {marker}", marker)
            self._complete_stage("dataset_create", "temporary dataset creation")

            client.read_dataset_row(dataset_key, marker)
            self._complete_stage("dataset_read", "temporary row retrieval")

            self.worker_probe.verify(marker, self.timeout)
            self._complete_stage("worker", "worker readiness")
            completed = True
        finally:
            cleanup_actions = []
            if client is not None:
                cleanup_actions.append(client.close)
            cleanup_actions.append(self.worker_probe.cleanup)
            if user is not None:
                cleanup_actions.append(user.delete)

            cleanup_failed = False
            for cleanup_action in cleanup_actions:
                try:
                    cleanup_action()
                except Exception:
                    cleanup_failed = True

            if cleanup_failed:
                self.report("error: one or more temporary-data cleanup actions failed")
                if completed:
                    raise SmokeTestError("Post-deployment smoke test cleanup failed.")
            else:
                self.report("ok: temporary data removed")

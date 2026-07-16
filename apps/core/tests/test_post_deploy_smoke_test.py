from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from starlette.testclient import TestClient

from apps.core.models import AgentApiKey, Profile
from apps.core.post_deploy_smoke import (
    SMOKE_STAGES,
    PostDeploySmokeClient,
    PostDeploySmokeRunner,
    SmokeTestError,
    WorkerReadinessProbe,
    validate_smoke_base_url,
    worker_readiness_task,
)
from apps.core.post_deploy_smoke_auth import SMOKE_HEADER, create_smoke_token
from apps.datasets.models import Dataset
from rowset.asgi import application


class FakeSmokeClient:
    def __init__(self, raw_key, smoke_token):
        self.raw_key = raw_key
        self.smoke_token = smoke_token
        self.calls = []

    def verify_rest_auth(self, expected_email):
        self.calls.append(("rest_auth", expected_email))

    def initialize_mcp(self):
        self.calls.append(("mcp_initialize",))

    def list_mcp_tools(self, required_tools):
        self.calls.append(("mcp_tools", tuple(required_tools)))

    def create_dataset(self, name, marker):
        self.calls.append(("dataset_create", name, marker))
        return "temporary-dataset-key"

    def read_dataset_row(self, dataset_key, marker):
        self.calls.append(("dataset_read", dataset_key, marker))

    def close(self):
        self.calls.append(("close",))


class FakeWorkerProbe:
    def __init__(self):
        self.calls = []

    def verify(self, marker, timeout):
        self.calls.append(("verify", marker, timeout))

    def cleanup(self):
        self.calls.append(("cleanup",))


def _runner(*, fail_after=None, report=None):
    clients = []
    worker_probe = FakeWorkerProbe()

    def client_factory(base_url, raw_key, timeout, smoke_token):
        assert base_url == "https://rowset.example"
        assert timeout == 7
        client = FakeSmokeClient(raw_key, smoke_token)
        clients.append(client)
        return client

    runner = PostDeploySmokeRunner(
        base_url="https://rowset.example",
        timeout=7,
        fail_after=fail_after,
        client_factory=client_factory,
        worker_probe=worker_probe,
        report=report or (lambda _message: None),
    )
    return runner, clients, worker_probe


@pytest.mark.django_db(transaction=True)
def test_authenticated_smoke_runs_every_stage_and_removes_temporary_data():
    runner, clients, worker_probe = _runner()

    runner.run()

    assert [call[0] for call in clients[0].calls] == [
        "rest_auth",
        "mcp_initialize",
        "mcp_tools",
        "dataset_create",
        "dataset_read",
        "close",
    ]
    assert clients[0].calls[2][1] == ("get_user_info", "list_dataset_rows")
    assert worker_probe.calls[0][0] == "verify"
    assert worker_probe.calls[-1] == ("cleanup",)
    assert not Profile.objects.filter(user__username__startswith="rowset-smoke-").exists()
    assert not AgentApiKey.objects.filter(name__startswith="Post-deploy smoke ").exists()
    assert not Dataset.objects.filter(name__startswith="Post-deploy smoke ").exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("fail_after", SMOKE_STAGES)
def test_authenticated_smoke_removes_temporary_data_after_each_stage_failure(fail_after):
    runner, clients, worker_probe = _runner(fail_after=fail_after)

    with pytest.raises(SmokeTestError, match=f"Forced failure after {fail_after}"):
        runner.run()

    assert not Profile.objects.filter(user__username__startswith="rowset-smoke-").exists()
    assert not AgentApiKey.objects.filter(name__startswith="Post-deploy smoke ").exists()
    assert not Dataset.objects.filter(name__startswith="Post-deploy smoke ").exists()
    assert worker_probe.calls[-1] == ("cleanup",)
    if clients:
        assert clients[0].calls[-1] == ("close",)


@pytest.mark.django_db(transaction=True)
def test_authenticated_smoke_is_repeatable():
    first, _first_clients, _first_worker = _runner()
    second, _second_clients, _second_worker = _runner()

    first.run()
    second.run()

    assert not Profile.objects.filter(user__username__startswith="rowset-smoke-").exists()


@pytest.mark.django_db(transaction=True)
def test_authenticated_smoke_never_reports_the_raw_api_key(monkeypatch):
    canary_key = "rsk_DO_NOT_LEAK_THIS_CANARY"
    messages = []
    runner, clients, _worker_probe = _runner(report=messages.append)

    def fake_create_agent_api_key(profile, name, access_level):
        AgentApiKey.objects.create(
            profile=profile,
            name=name,
            access_level=access_level,
            key_prefix="rsk_DO_NOT_LE",
            token_hash="canary-token-hash",
        )
        return SimpleNamespace(raw_key=canary_key)

    monkeypatch.setattr(
        "apps.core.post_deploy_smoke.create_agent_api_key",
        fake_create_agent_api_key,
    )

    runner.run()

    assert clients[0].raw_key == canary_key
    assert canary_key not in "\n".join(messages)


@pytest.mark.django_db(transaction=True)
def test_authenticated_smoke_attempts_all_cleanup_when_one_cleanup_action_fails(monkeypatch):
    runner, _clients, worker_probe = _runner()

    def fail_client_close(self):
        raise RuntimeError("close failed")

    monkeypatch.setattr(FakeSmokeClient, "close", fail_client_close)

    with pytest.raises(SmokeTestError, match="cleanup failed"):
        runner.run()

    assert worker_probe.calls[-1] == ("cleanup",)
    assert not Profile.objects.filter(user__username__startswith="rowset-smoke-").exists()
    assert not AgentApiKey.objects.filter(name__startswith="Post-deploy smoke ").exists()


@pytest.mark.django_db(transaction=True)
def test_authenticated_smoke_rolls_back_partial_identity_setup(monkeypatch):
    runner, _clients, worker_probe = _runner()
    monkeypatch.setattr(
        "apps.core.post_deploy_smoke.create_agent_api_key",
        Mock(side_effect=RuntimeError("key creation failed")),
    )

    with pytest.raises(RuntimeError, match="key creation failed"):
        runner.run()

    assert worker_probe.calls[-1] == ("cleanup",)
    assert not Profile.objects.filter(user__username__startswith="rowset-smoke-").exists()


@pytest.mark.django_db(transaction=True)
def test_authenticated_smoke_crosses_real_rest_and_mcp_boundaries():
    worker_probe = FakeWorkerProbe()

    class AsgiSession:
        def __init__(self, raw_key, smoke_token):
            self.client = TestClient(
                application,
                headers={
                    "Authorization": f"Bearer {raw_key}",
                    "Accept": "application/json, text/event-stream",
                    SMOKE_HEADER: smoke_token,
                },
            )
            self.client.__enter__()

        def request(self, method, url, **kwargs):
            kwargs.pop("timeout", None)
            return self.client.request(method, url, **kwargs)

        def close(self):
            self.client.__exit__(None, None, None)

    def asgi_client_factory(base_url, raw_key, timeout, smoke_token):
        client = PostDeploySmokeClient(base_url, raw_key, timeout, smoke_token)
        client.session.close()
        client.session = AsgiSession(raw_key, smoke_token)
        return client

    runner = PostDeploySmokeRunner(
        base_url="http://testserver",
        timeout=7,
        client_factory=asgi_client_factory,
        worker_probe=worker_probe,
    )

    runner.run()

    assert worker_probe.calls[0][0] == "verify"
    assert not Profile.objects.filter(user__username__startswith="rowset-smoke-").exists()
    assert not Dataset.objects.filter(name__startswith="Post-deploy smoke ").exists()


def test_worker_probe_uses_an_atomic_non_persistent_handshake(monkeypatch):
    connection = Mock()
    connection.get.return_value = b"marker"
    broker = SimpleNamespace(connection=connection, list_key="django-q", enqueue=Mock())
    delete = Mock()
    monkeypatch.setattr(
        "apps.core.post_deploy_smoke.SignedPackage.dumps",
        lambda _package: "signed-package",
    )
    monkeypatch.setattr("apps.core.post_deploy_smoke.Task.objects.filter", delete)
    probe = WorkerReadinessProbe(broker=broker)

    probe.verify("marker", 7.5)
    probe.cleanup()

    active_key = "rowset:post-deploy-smoke:marker:active"
    result_key = "rowset:post-deploy-smoke:marker:result"
    connection.set.assert_called_once_with(active_key, "marker", ex=68)
    broker.enqueue.assert_called_once_with("signed-package")
    connection.lrem.assert_called_once_with("django-q", 1, "signed-package")
    connection.delete.assert_called_once_with(active_key, result_key)
    delete.assert_called_once_with(id=probe.task_id)


def test_worker_readiness_publish_failure_does_not_create_a_failed_task(monkeypatch):
    connection = Mock()
    connection.eval.side_effect = RuntimeError("redis unavailable")
    monkeypatch.setattr(
        "apps.core.post_deploy_smoke.get_broker",
        lambda: SimpleNamespace(connection=connection),
    )

    assert worker_readiness_task("marker") is None


def test_worker_probe_removes_its_unconsumed_queue_package(monkeypatch):
    connection = Mock()
    connection.get.return_value = b"marker"
    broker = SimpleNamespace(connection=connection, list_key="django-q", enqueue=Mock())
    monkeypatch.setattr(
        "apps.core.post_deploy_smoke.SignedPackage.dumps",
        lambda _package: "signed-package",
    )
    delete = Mock()
    monkeypatch.setattr("apps.core.post_deploy_smoke.Task.objects.filter", delete)
    probe = WorkerReadinessProbe(broker=broker)

    probe.verify("marker", 7.5)
    probe.cleanup()

    connection.lrem.assert_called_once_with("django-q", 1, "signed-package")
    delete.assert_called_once()


def test_worker_cleanup_attempts_each_resource_after_queue_failure(monkeypatch):
    connection = Mock()
    connection.get.return_value = b"marker"
    connection.lrem.side_effect = RuntimeError("redis queue unavailable")
    broker = SimpleNamespace(connection=connection, list_key="django-q", enqueue=Mock())
    monkeypatch.setattr(
        "apps.core.post_deploy_smoke.SignedPackage.dumps",
        lambda _package: "signed-package",
    )
    delete = Mock()
    monkeypatch.setattr("apps.core.post_deploy_smoke.Task.objects.filter", delete)
    probe = WorkerReadinessProbe(broker=broker)
    probe.verify("marker", 7.5)

    with pytest.raises(SmokeTestError, match="cleanup failed"):
        probe.cleanup()

    delete.assert_called_once()
    connection.delete.assert_called_once_with(
        "rowset:post-deploy-smoke:marker:active",
        "rowset:post-deploy-smoke:marker:result",
    )


def test_smoke_http_client_marks_internal_requests_without_exposing_the_key():
    smoke_token = create_smoke_token("marker")
    client = PostDeploySmokeClient("https://rowset.example", "rsk_private", 5, smoke_token)

    assert client.session.headers[SMOKE_HEADER] == smoke_token
    assert "rsk_private" not in client.session.headers[SMOKE_HEADER]

    client.close()


@pytest.mark.parametrize(
    "base_url",
    [
        "http://rowset.example",
        "https://lookalike.example",
        "https://user:password@rowset.example",
        "https://rowset.example/path",
    ],
)
def test_smoke_base_url_rejects_credential_exfiltration_targets(base_url):
    with pytest.raises(ValueError):
        validate_smoke_base_url(base_url, "https://rowset.example")


@pytest.mark.parametrize(
    "base_url",
    ["https://rowset.example", "http://127.0.0.1:8016", "http://backend:8016"],
)
def test_smoke_base_url_accepts_configured_and_internal_origins(base_url):
    validate_smoke_base_url(base_url, "https://rowset.example")

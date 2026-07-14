import os
import subprocess
import sys
from pathlib import Path

import pytest
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError

from deployment.healthcheck import check_worker

_REPO_ROOT = Path(__file__).parents[2]


@pytest.mark.django_db
def test_worker_healthcheck_fails_when_redis_is_unavailable(settings):
    settings.REDIS_URL = "redis://127.0.0.1:1/0"

    with pytest.raises(RedisConnectionError):
        check_worker()


@pytest.mark.django_db
def test_worker_healthcheck_fails_when_redis_rejects_writes(monkeypatch):
    class ReadOnlyRedis:
        def set(self, *args, **kwargs):
            raise ResponseError("READONLY")

        def close(self):
            pass

    monkeypatch.setattr(Redis, "from_url", lambda *args, **kwargs: ReadOnlyRedis())

    with pytest.raises(ResponseError, match="READONLY"):
        check_worker()


def test_worker_healthcheck_module_returns_nonzero_when_redis_is_unavailable():
    env = os.environ.copy()
    env.update({"REDIS_HOST": "127.0.0.1", "REDIS_PORT": "1"})

    result = subprocess.run(
        [sys.executable, "-m", "deployment.healthcheck", "worker"],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 1
    assert "Healthcheck failed:" in result.stderr
    assert "127.0.0.1:1" in result.stderr

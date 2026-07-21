import json
from collections.abc import Sequence

import pytest
from django.test import override_settings
from opentelemetry.sdk.trace import SpanLimits, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai import Agent, Embedder
from pydantic_ai.embeddings import TestEmbeddingModel
from pydantic_ai.embeddings.result import EmbeddingResult, EmbedInputType
from pydantic_ai.embeddings.settings import EmbeddingSettings
from pydantic_ai.models.instrumented import InstrumentationSettings
from pydantic_ai.models.test import TestModel

from apps.core import ai_observability


def _privacy_safe_provider():
    exporter = InMemorySpanExporter()
    provider = TracerProvider(span_limits=SpanLimits(max_events=0))
    provider.add_span_processor(
        ai_observability.PrivacySafeSpanProcessor(SimpleSpanProcessor(exporter))
    )
    return provider, exporter


def _serialized_spans(exporter):
    return [json.loads(span.to_json(indent=None)) for span in exporter.get_finished_spans()]


@pytest.fixture(autouse=True)
def reset_global_instrumentation():
    agent_instrumentation = Agent._instrument_default
    embedder_instrumentation = Embedder._instrument_default
    yield
    Agent._instrument_default = agent_instrumentation
    Embedder._instrument_default = embedder_instrumentation


@override_settings(POSTHOG_AI_OBSERVABILITY_ENABLED=False, POSTHOG_API_KEY="phc_test")
def test_configure_ai_observability_is_optional(monkeypatch):
    processor_calls = []
    monkeypatch.setattr(
        ai_observability,
        "PostHogSpanProcessor",
        lambda **kwargs: processor_calls.append(kwargs),
    )

    result = ai_observability.configure_ai_observability()

    assert result is None
    assert processor_calls == []


@override_settings(
    POSTHOG_AI_OBSERVABILITY_ENABLED=True,
    POSTHOG_API_KEY="phc_test",
    POSTHOG_HOST="https://eu.i.posthog.com",
    POSTHOG_SERVICE_NAME="rowset-worker",
    POSTHOG_SERVICE_VERSION="abc123",
    ENVIRONMENT="prod",
)
def test_configure_ai_observability_instruments_pydantic_ai_without_content(monkeypatch):
    calls = []
    providers = []
    processor = object()

    class FakeTracerProvider:
        def __init__(self, *, resource, span_limits):
            providers.append(self)
            calls.append(("provider", resource.attributes, span_limits))

        def add_span_processor(self, configured_processor):
            calls.append(("processor", configured_processor))

        def get_tracer(self, *args):
            return object()

        def shutdown(self):
            calls.append(("shutdown",))

    monkeypatch.setattr(ai_observability, "TracerProvider", FakeTracerProvider)
    monkeypatch.setattr(
        ai_observability,
        "PostHogSpanProcessor",
        lambda **kwargs: calls.append(("posthog", kwargs)) or processor,
    )
    monkeypatch.setattr(
        ai_observability.Embedder,
        "instrument_all",
        lambda instrumentation: calls.append(("embedder", instrumentation)),
    )
    monkeypatch.setattr(
        ai_observability.Agent,
        "instrument_all",
        lambda instrumentation: calls.append(("agent", instrumentation)),
    )
    monkeypatch.setattr(
        ai_observability.atexit,
        "register",
        lambda callback: calls.append(("atexit", callback)),
    )

    result = ai_observability.configure_ai_observability()

    assert result is None
    assert len(providers) == 1
    assert calls[0][0:2] == (
        "provider",
        {
            "service.name": "rowset-worker",
            "service.version": "abc123",
            "deployment.environment.name": "prod",
        },
    )
    assert calls[0][2].max_events == 0
    assert calls[1] == (
        "posthog",
        {"api_key": "phc_test", "host": "https://eu.i.posthog.com"},
    )
    configured_processor = calls[2][1]
    assert isinstance(configured_processor, ai_observability.PrivacySafeSpanProcessor)
    assert configured_processor.processor is processor

    embedder_instrumentation = calls[3][1]
    agent_instrumentation = calls[4][1]
    assert embedder_instrumentation is agent_instrumentation
    assert embedder_instrumentation.include_content is False
    assert embedder_instrumentation.include_binary_content is False
    assert calls[5] == ("atexit", providers[0].shutdown)


@override_settings(
    POSTHOG_AI_OBSERVABILITY_ENABLED=True,
    POSTHOG_API_KEY="phc_test",
    POSTHOG_HOST="https://us.i.posthog.com",
    POSTHOG_SERVICE_NAME="rowset-web",
    POSTHOG_SERVICE_VERSION="test",
    ENVIRONMENT="test",
)
def test_configure_ai_observability_fails_open_when_processor_setup_fails(monkeypatch):
    calls = []

    class PrivateProcessorError(RuntimeError):
        pass

    class FakeTracerProvider:
        def __init__(self, **kwargs):
            calls.append(("provider", kwargs))

        def shutdown(self):
            calls.append(("shutdown",))

    monkeypatch.setattr(ai_observability, "TracerProvider", FakeTracerProvider)
    monkeypatch.setattr(
        ai_observability,
        "PostHogSpanProcessor",
        lambda **kwargs: (_ for _ in ()).throw(PrivateProcessorError("private-key-content")),
    )
    monkeypatch.setattr(
        ai_observability.logger,
        "error",
        lambda event, **kwargs: calls.append(("log", event, kwargs)),
    )

    assert ai_observability.configure_ai_observability() is None
    assert calls[-2:] == [
        ("shutdown",),
        (
            "log",
            "posthog.ai_observability.setup_failed",
            {"error_type": "PrivateProcessorError"},
        ),
    ]
    assert "private-key-content" not in json.dumps(calls, default=str)


@override_settings(
    POSTHOG_AI_OBSERVABILITY_ENABLED=True,
    POSTHOG_API_KEY="phc_test",
    POSTHOG_HOST="https://us.i.posthog.com",
    POSTHOG_SERVICE_NAME="rowset-web",
    POSTHOG_SERVICE_VERSION="test",
    ENVIRONMENT="test",
)
def test_configure_ai_observability_rolls_back_after_instrumentation_failure(monkeypatch):
    calls = []
    previous_agent_instrumentation = object()
    previous_embedder_instrumentation = object()
    Agent._instrument_default = previous_agent_instrumentation
    Embedder._instrument_default = previous_embedder_instrumentation

    class PrivateInstrumentationError(RuntimeError):
        pass

    class FakeTracerProvider:
        def __init__(self, **kwargs):
            calls.append(("provider", kwargs))

        def add_span_processor(self, processor):
            calls.append(("processor", processor))

        def get_tracer(self, *args):
            return object()

        def shutdown(self):
            calls.append(("shutdown",))

    monkeypatch.setattr(ai_observability, "TracerProvider", FakeTracerProvider)
    monkeypatch.setattr(ai_observability, "PostHogSpanProcessor", lambda **kwargs: object())
    monkeypatch.setattr(
        ai_observability.Agent,
        "instrument_all",
        lambda instrumentation: (_ for _ in ()).throw(
            PrivateInstrumentationError("private-provider-body")
        ),
    )
    monkeypatch.setattr(
        ai_observability.logger,
        "error",
        lambda event, **kwargs: calls.append(("log", event, kwargs)),
    )
    monkeypatch.setattr(
        ai_observability.atexit,
        "register",
        lambda callback: calls.append(("atexit", callback)),
    )

    assert ai_observability.configure_ai_observability() is None
    assert Agent._instrument_default is previous_agent_instrumentation
    assert Embedder._instrument_default is previous_embedder_instrumentation
    assert ("shutdown",) in calls
    assert not any(call[0] == "atexit" for call in calls)
    assert calls[-1] == (
        "log",
        "posthog.ai_observability.setup_failed",
        {"error_type": "PrivateInstrumentationError"},
    )
    assert "private-provider-body" not in json.dumps(calls, default=str)


def test_private_instrumentation_emits_embedding_metadata_without_input():
    provider, exporter = _privacy_safe_provider()
    instrumentation = InstrumentationSettings(
        tracer_provider=provider,
        include_content=False,
        include_binary_content=False,
    )

    Embedder(
        TestEmbeddingModel(model_name="embed-test", provider_name="test"),
        instrument=instrumentation,
    ).embed_query_sync("private customer dataset text")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    attributes = dict(spans[0].attributes)
    assert attributes["gen_ai.operation.name"] == "embeddings"
    assert attributes["gen_ai.request.model"] == "embed-test"
    assert attributes["gen_ai.usage.input_tokens"] == 4
    assert "private customer dataset text" not in json.dumps(_serialized_spans(exporter))
    assert "gen_ai.input.messages" not in attributes
    assert spans[0].events == ()
    provider.shutdown()


def test_failing_embedding_excludes_private_exception_content_from_exported_span():
    private_sentinel = "private-provider-body-48d1d269"

    class FailingEmbeddingModel(TestEmbeddingModel):
        async def embed(
            self,
            inputs: str | Sequence[str],
            *,
            input_type: EmbedInputType,
            settings: EmbeddingSettings | None = None,
        ) -> EmbeddingResult:
            raise RuntimeError(private_sentinel)

    provider, exporter = _privacy_safe_provider()
    instrumentation = InstrumentationSettings(
        tracer_provider=provider,
        include_content=False,
        include_binary_content=False,
    )
    embedder = Embedder(
        FailingEmbeddingModel(model_name="failing-embed-test", provider_name="test"),
        instrument=instrumentation,
    )

    with pytest.raises(RuntimeError, match=private_sentinel):
        embedder.embed_query_sync("private embedding input")

    serialized_spans = _serialized_spans(exporter)
    assert len(serialized_spans) == 1
    assert serialized_spans[0]["attributes"]["gen_ai.operation.name"] == "embeddings"
    assert serialized_spans[0]["attributes"]["gen_ai.request.model"] == "failing-embed-test"
    assert serialized_spans[0]["events"] == []
    assert serialized_spans[0]["status"] == {"status_code": "ERROR"}
    assert private_sentinel not in json.dumps(serialized_spans)
    provider.shutdown()


def test_agent_integration_exports_metadata_without_prompt_response_or_tool_content():
    prompt_sentinel = "private-prompt-d6f8ef57"
    response_sentinel = "private-response-f6db6b3f"
    tool_argument_sentinel = "private-tool-argument-faa8e0a2"
    tool_result_sentinel = "private-tool-result-0f00621b"

    class PrivateToolArgumentTestModel(TestModel):
        def gen_tool_args(self, tool_def):
            return {"secret": tool_argument_sentinel}

    provider, exporter = _privacy_safe_provider()
    instrumentation = InstrumentationSettings(
        tracer_provider=provider,
        include_content=False,
        include_binary_content=False,
    )
    agent = Agent(
        PrivateToolArgumentTestModel(
            call_tools=["private_lookup"],
            custom_output_text=response_sentinel,
            model_name="agent-test-model",
        ),
        name="privacy-test-agent",
    )
    agent.instrument = instrumentation

    @agent.tool_plain
    def private_lookup(secret: str) -> str:
        assert secret == tool_argument_sentinel
        return tool_result_sentinel

    result = agent.run_sync(prompt_sentinel)

    assert result.output == response_sentinel
    serialized_spans = _serialized_spans(exporter)
    serialized_json = json.dumps(serialized_spans)
    for sentinel in (
        prompt_sentinel,
        response_sentinel,
        tool_argument_sentinel,
        tool_result_sentinel,
    ):
        assert sentinel not in serialized_json
    assert all(span["events"] == [] for span in serialized_spans)
    operations = {span["attributes"].get("gen_ai.operation.name") for span in serialized_spans}
    assert {"invoke_agent", "chat", "execute_tool"} <= operations
    assert any(
        span["attributes"].get("gen_ai.request.model") == "agent-test-model"
        for span in serialized_spans
    )
    assert any(
        span["attributes"].get("gen_ai.agent.name") == "privacy-test-agent"
        for span in serialized_spans
    )
    provider.shutdown()

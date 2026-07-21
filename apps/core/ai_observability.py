import atexit

from django.conf import settings
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanLimits, SpanProcessor, TracerProvider
from opentelemetry.trace import Status
from posthog.ai.otel import PostHogSpanProcessor
from pydantic_ai import Agent, Embedder
from pydantic_ai.models.instrumented import InstrumentationSettings

from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)


class PrivacySafeSpanProcessor(SpanProcessor):
    """Remove exception payloads before forwarding AI spans to an exporter."""

    def __init__(self, processor: SpanProcessor):
        self.processor = processor

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        self.processor.on_start(span, parent_context=parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        safe_span = ReadableSpan(
            name=span.name,
            context=span.context,
            parent=span.parent,
            resource=span.resource,
            attributes=span.attributes,
            events=(),
            links=span.links,
            kind=span.kind,
            status=Status(span.status.status_code),
            start_time=span.start_time,
            end_time=span.end_time,
            instrumentation_scope=span.instrumentation_scope,
        )
        self.processor.on_end(safe_span)

    def shutdown(self) -> None:
        self.processor.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.processor.force_flush(timeout_millis)


def configure_ai_observability() -> None:
    """Export privacy-safe Pydantic AI traces to PostHog when configured."""
    if not settings.POSTHOG_AI_OBSERVABILITY_ENABLED or not settings.POSTHOG_API_KEY:
        return

    previous_agent_instrumentation = Agent._instrument_default
    previous_embedder_instrumentation = Embedder._instrument_default
    provider = None

    try:
        resource = Resource(
            attributes={
                "service.name": settings.POSTHOG_SERVICE_NAME,
                "service.version": settings.POSTHOG_SERVICE_VERSION,
                "deployment.environment.name": settings.ENVIRONMENT,
            }
        )
        provider = TracerProvider(resource=resource, span_limits=SpanLimits(max_events=0))
        processor = PostHogSpanProcessor(
            api_key=settings.POSTHOG_API_KEY,
            host=settings.POSTHOG_HOST,
        )
        provider.add_span_processor(PrivacySafeSpanProcessor(processor))

        instrumentation = InstrumentationSettings(
            tracer_provider=provider,
            include_content=False,
            include_binary_content=False,
        )
        Embedder.instrument_all(instrumentation)
        Agent.instrument_all(instrumentation)
        atexit.register(provider.shutdown)
    except Exception as exc:
        Agent._instrument_default = previous_agent_instrumentation
        Embedder._instrument_default = previous_embedder_instrumentation
        if provider is not None:
            try:
                provider.shutdown()
            except Exception:
                pass
        logger.error(
            "posthog.ai_observability.setup_failed",
            error_type=type(exc).__name__,
        )

import hashlib
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from openai import OpenAI, OpenAIError

from apps.datasets.vector_search import qdrant_is_enabled


class EmbeddingProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    model: str
    dimensions: int


class EmbeddingProvider(Protocol):
    @property
    def model(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    def embed_text(self, text: str) -> EmbeddingResult: ...

    def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]: ...


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        *,
        client=None,
        api_key: str | None = None,
        model: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        self.model = model or settings.ROWSET_EMBEDDING_MODEL
        self.dimensions = dimensions or settings.ROWSET_EMBEDDING_DIMENSIONS
        self.client = client or OpenAI(api_key=api_key or settings.OPENAI_API_KEY)

    def embed_text(self, text: str) -> EmbeddingResult:
        return self._embed(text)[0]

    def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        if not texts:
            return []
        return self._embed(texts)

    def _embed(self, input_value: str | list[str]) -> list[EmbeddingResult]:
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=input_value,
                dimensions=self.dimensions,
            )
        except OpenAIError as exc:
            raise EmbeddingProviderError(f"OpenAI embedding request failed: {exc}") from exc
        results = []
        for item in response.data:
            vector = list(item.embedding)
            if len(vector) != self.dimensions:
                raise ValueError(
                    f"Expected embedding with {self.dimensions} dimensions, got {len(vector)}."
                )
            results.append(
                EmbeddingResult(
                    vector=vector,
                    model=self.model,
                    dimensions=self.dimensions,
                )
            )
        return results


_CACHED_PROVIDER_KEY: tuple[str, int, str] | None = None
_CACHED_PROVIDER: OpenAIEmbeddingProvider | None = None
_CACHED_PROVIDER_LOCK = Lock()


def _api_key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _cached_openai_embedding_provider(
    api_key: str,
    model: str,
    dimensions: int,
) -> OpenAIEmbeddingProvider:
    global _CACHED_PROVIDER, _CACHED_PROVIDER_KEY

    cache_key = (model, dimensions, _api_key_fingerprint(api_key))
    with _CACHED_PROVIDER_LOCK:
        if _CACHED_PROVIDER is None or _CACHED_PROVIDER_KEY != cache_key:
            provider = OpenAIEmbeddingProvider(
                api_key=api_key,
                model=model,
                dimensions=dimensions,
            )
            _CACHED_PROVIDER = provider
            _CACHED_PROVIDER_KEY = cache_key
        return _CACHED_PROVIDER


def get_embedding_provider() -> EmbeddingProvider:
    if not qdrant_is_enabled():
        raise ImproperlyConfigured(
            "ROWSET_VECTOR_SEARCH_ENABLED must be true before embedding rows."
        )
    api_key = str(settings.OPENAI_API_KEY or "").strip()
    if not api_key:
        raise ImproperlyConfigured("OPENAI_API_KEY must be configured before embedding rows.")
    return _cached_openai_embedding_provider(
        api_key,
        settings.ROWSET_EMBEDDING_MODEL,
        settings.ROWSET_EMBEDDING_DIMENSIONS,
    )

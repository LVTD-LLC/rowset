import hashlib
import math
from dataclasses import dataclass
from itertools import batched
from threading import Lock
from typing import Protocol

import tiktoken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from pydantic_ai import Embedder
from pydantic_ai.embeddings import EmbeddingSettings
from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.providers.openai import OpenAIProvider

from apps.datasets.vector_search import qdrant_is_enabled

OPENAI_EMBEDDING_MAX_TOKENS = 8191
# 32 * 8191 stays below the provider's 300,000-token request limit.
EMBEDDING_BATCH_SIZE = 32
OPENAI_EMBEDDING_MODELS = {
    "text-embedding-3-small",
    "text-embedding-3-large",
    "text-embedding-ada-002",
}


def _embedding_chunks(text: str, model: str) -> list[tuple[str, int]]:
    """Split only known OpenAI models; preserve every Unicode character."""
    if model.removeprefix("openai/") not in OPENAI_EMBEDDING_MODELS:
        return [(text, 1)]
    encoding = tiktoken.get_encoding("cl100k_base")
    pending = [text]
    chunks = []
    while pending:
        chunk = pending.pop()
        # Treat token-like literals in user data as ordinary text.
        count = len(encoding.encode_ordinary(chunk))
        if count <= OPENAI_EMBEDDING_MAX_TOKENS:
            chunks.append((chunk, count))
        else:
            # Splitting the string, not decoded token slices, avoids corrupting
            # multibyte characters. Recount each half after its boundary changes.
            midpoint = len(chunk) // 2
            pending.extend((chunk[midpoint:], chunk[:midpoint]))
    return chunks


def _combine_embeddings(results: list[EmbeddingResult], weights: list[int]) -> EmbeddingResult:
    if len(results) == 1:
        return results[0]
    vector = [
        sum(result.vector[index] * weight for result, weight in zip(results, weights, strict=True))
        for index in range(results[0].dimensions)
    ]
    norm = math.hypot(*vector)
    if norm:
        vector = [value / norm for value in vector]
    return EmbeddingResult(vector, results[0].model, results[0].dimensions)


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


class OpenRouterPydanticAIEmbeddingProvider:
    def __init__(
        self,
        *,
        embedder: Embedder | None = None,
        api_key: str | None = None,
        model: str | None = None,
        dimensions: int | None = None,
        base_url: str | None = None,
    ) -> None:
        self.model = model or settings.ROWSET_EMBEDDING_MODEL
        self.dimensions = dimensions or settings.ROWSET_EMBEDDING_DIMENSIONS
        self.embedder = embedder or self._build_embedder(
            api_key=api_key or settings.OPENROUTER_API_KEY,
            base_url=base_url or settings.OPENROUTER_BASE_URL,
        )

    def _build_embedder(self, *, api_key: str, base_url: str) -> Embedder:
        # OpenRouter's embeddings router is OpenAI-compatible; PydanticAI exposes
        # that path through OpenAIEmbeddingModel plus a custom provider base URL.
        model = OpenAIEmbeddingModel(
            self.model,
            provider=OpenAIProvider(base_url=base_url, api_key=api_key),
        )
        return Embedder(
            model,
            settings=EmbeddingSettings(
                dimensions=self.dimensions,
                extra_headers={
                    "HTTP-Referer": settings.SITE_URL,
                    "X-OpenRouter-Title": "Rowset",
                },
            ),
        )

    def embed_text(self, text: str) -> EmbeddingResult:
        chunks = _embedding_chunks(text, self.model)
        results = [self._embed_query(chunk)[0] for chunk, _ in chunks]
        return _combine_embeddings(results, [weight for _, weight in chunks])

    def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        if not texts:
            return []
        documents = [_embedding_chunks(text, self.model) for text in texts]
        chunks = [chunk for document in documents for chunk, _ in document]
        results = []
        for batch in batched(chunks, EMBEDDING_BATCH_SIZE, strict=False):
            results.extend(self._embed_documents(list(batch)))
        combined = []
        offset = 0
        for document in documents:
            end = offset + len(document)
            combined.append(
                _combine_embeddings(results[offset:end], [weight for _, weight in document])
            )
            offset = end
        return combined

    def _embed_query(self, text: str) -> list[EmbeddingResult]:
        try:
            response = self.embedder.embed_query_sync(text)
        except ModelHTTPError as exc:
            raise EmbeddingProviderError(f"OpenRouter embedding request failed: {exc}") from exc
        return self._embedding_results(response.embeddings, expected_count=1)

    def _embed_documents(self, texts: list[str]) -> list[EmbeddingResult]:
        try:
            response = self.embedder.embed_documents_sync(texts)
        except ModelHTTPError as exc:
            raise EmbeddingProviderError(f"OpenRouter embedding request failed: {exc}") from exc
        return self._embedding_results(response.embeddings, expected_count=len(texts))

    def _embedding_results(self, embeddings, *, expected_count: int) -> list[EmbeddingResult]:
        results = []
        for embedding in embeddings:
            vector = list(embedding)
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
        if len(results) != expected_count:
            raise EmbeddingProviderError(
                f"Expected {expected_count} embeddings, got {len(results)}."
            )
        return results


_CACHED_PROVIDER_KEY: tuple[str, int, str] | None = None
_CACHED_PROVIDER: OpenRouterPydanticAIEmbeddingProvider | None = None
_CACHED_PROVIDER_LOCK = Lock()


def _api_key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _cached_openrouter_embedding_provider(
    api_key: str,
    base_url: str,
    model: str,
    dimensions: int,
) -> OpenRouterPydanticAIEmbeddingProvider:
    global _CACHED_PROVIDER, _CACHED_PROVIDER_KEY

    cache_key = (model, dimensions, _api_key_fingerprint(f"{base_url}:{api_key}"))
    with _CACHED_PROVIDER_LOCK:
        if _CACHED_PROVIDER is None or _CACHED_PROVIDER_KEY != cache_key:
            provider = OpenRouterPydanticAIEmbeddingProvider(
                api_key=api_key,
                base_url=base_url,
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
    api_key = str(settings.OPENROUTER_API_KEY or "").strip()
    if not api_key:
        raise ImproperlyConfigured("OPENROUTER_API_KEY must be configured before embedding rows.")
    base_url = str(settings.OPENROUTER_BASE_URL or "").strip()
    if not base_url:
        raise ImproperlyConfigured("OPENROUTER_BASE_URL must be configured before embedding rows.")
    return _cached_openrouter_embedding_provider(
        api_key,
        base_url,
        settings.ROWSET_EMBEDDING_MODEL,
        settings.ROWSET_EMBEDDING_DIMENSIONS,
    )

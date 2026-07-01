from types import SimpleNamespace

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from pydantic_ai.exceptions import ModelHTTPError

from apps.datasets.embeddings import (
    EmbeddingProviderError,
    EmbeddingResult,
    OpenRouterPydanticAIEmbeddingProvider,
    get_embedding_provider,
)


class FakePydanticAIEmbedder:
    def __init__(self, vectors, *, error=None):
        self.vectors = vectors
        self.error = error
        self.calls = []

    def embed_query_sync(self, query):
        self.calls.append(("query", query))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(embeddings=[self.vectors])

    def embed_documents_sync(self, documents):
        self.calls.append(("documents", documents))
        if self.error is not None:
            raise self.error
        vectors = self.vectors
        if vectors and not isinstance(vectors[0], list):
            vectors = [vectors]
        return SimpleNamespace(embeddings=vectors)


def test_openrouter_embedding_provider_embeds_text_with_configured_model_and_dimensions():
    embedder = FakePydanticAIEmbedder([0.1, 0.2, 0.3])
    provider = OpenRouterPydanticAIEmbeddingProvider(
        embedder=embedder,
        model="openai/text-embedding-3-small",
        dimensions=3,
    )

    result = provider.embed_text("Dataset: Tasks\nTitle: Add vector search")

    assert result == EmbeddingResult(
        vector=[0.1, 0.2, 0.3],
        model="openai/text-embedding-3-small",
        dimensions=3,
    )
    assert embedder.calls == [("query", "Dataset: Tasks\nTitle: Add vector search")]


def test_openrouter_embedding_provider_rejects_dimension_mismatch():
    provider = OpenRouterPydanticAIEmbeddingProvider(
        embedder=FakePydanticAIEmbedder([0.1, 0.2]),
        model="openai/text-embedding-3-small",
        dimensions=3,
    )

    with pytest.raises(ValueError, match="Expected embedding with 3 dimensions"):
        provider.embed_text("short text")


def test_openrouter_embedding_provider_embeds_texts_in_one_request():
    embedder = FakePydanticAIEmbedder([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
    provider = OpenRouterPydanticAIEmbeddingProvider(
        embedder=embedder,
        model="openai/text-embedding-3-small",
        dimensions=3,
    )

    results = provider.embed_texts(["first row", "second row"])

    assert results == [
        EmbeddingResult(
            vector=[0.1, 0.2, 0.3],
            model="openai/text-embedding-3-small",
            dimensions=3,
        ),
        EmbeddingResult(
            vector=[0.4, 0.5, 0.6],
            model="openai/text-embedding-3-small",
            dimensions=3,
        ),
    ]
    assert embedder.calls == [("documents", ["first row", "second row"])]


def test_openrouter_embedding_provider_wraps_provider_errors():
    provider = OpenRouterPydanticAIEmbeddingProvider(
        embedder=FakePydanticAIEmbedder(
            [],
            error=ModelHTTPError(401, "openai/text-embedding-3-small", body="unauthorized"),
        ),
        model="openai/text-embedding-3-small",
        dimensions=3,
    )

    with pytest.raises(EmbeddingProviderError, match="OpenRouter embedding request failed"):
        provider.embed_text("short text")


def test_openrouter_embedding_provider_does_not_wrap_internal_errors():
    provider = OpenRouterPydanticAIEmbeddingProvider(
        embedder=FakePydanticAIEmbedder([], error=TypeError("bad embedder call")),
        model="openai/text-embedding-3-small",
        dimensions=3,
    )

    with pytest.raises(TypeError, match="bad embedder call"):
        provider.embed_text("short text")


def test_get_embedding_provider_requires_vector_search_feature_flag():
    with override_settings(ROWSET_VECTOR_SEARCH_ENABLED=False, OPENROUTER_API_KEY="sk-test"):
        with pytest.raises(ImproperlyConfigured, match="ROWSET_VECTOR_SEARCH_ENABLED"):
            get_embedding_provider()


def test_get_embedding_provider_requires_openrouter_api_key():
    with override_settings(ROWSET_VECTOR_SEARCH_ENABLED=True, OPENROUTER_API_KEY=""):
        with pytest.raises(ImproperlyConfigured, match="OPENROUTER_API_KEY"):
            get_embedding_provider()


def test_get_embedding_provider_requires_openrouter_base_url():
    with override_settings(
        ROWSET_VECTOR_SEARCH_ENABLED=True,
        OPENROUTER_API_KEY="sk-test",
        OPENROUTER_BASE_URL="",
    ):
        with pytest.raises(ImproperlyConfigured, match="OPENROUTER_BASE_URL"):
            get_embedding_provider()


def test_get_embedding_provider_reuses_configured_provider():
    with override_settings(
        ROWSET_VECTOR_SEARCH_ENABLED=True,
        OPENROUTER_API_KEY="sk-test-cache",
        OPENROUTER_BASE_URL="https://openrouter.ai/api/v1",
        ROWSET_EMBEDDING_MODEL="openai/text-embedding-3-small",
        ROWSET_EMBEDDING_DIMENSIONS=3,
    ):
        first = get_embedding_provider()
        second = get_embedding_provider()

    assert first is second


def test_get_embedding_provider_refreshes_when_api_key_changes():
    with override_settings(
        ROWSET_VECTOR_SEARCH_ENABLED=True,
        OPENROUTER_API_KEY="sk-test-cache-a",
        OPENROUTER_BASE_URL="https://openrouter.ai/api/v1",
        ROWSET_EMBEDDING_MODEL="openai/text-embedding-3-small",
        ROWSET_EMBEDDING_DIMENSIONS=3,
    ):
        first = get_embedding_provider()

    with override_settings(
        ROWSET_VECTOR_SEARCH_ENABLED=True,
        OPENROUTER_API_KEY="sk-test-cache-b",
        OPENROUTER_BASE_URL="https://openrouter.ai/api/v1",
        ROWSET_EMBEDDING_MODEL="openai/text-embedding-3-small",
        ROWSET_EMBEDDING_DIMENSIONS=3,
    ):
        second = get_embedding_provider()

    assert first is not second

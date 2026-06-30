from types import SimpleNamespace

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from openai import OpenAIError

from apps.datasets.embeddings import (
    EmbeddingProviderError,
    EmbeddingResult,
    OpenAIEmbeddingProvider,
    get_embedding_provider,
)


class FakeEmbeddingsClient:
    def __init__(self, vectors, *, error=None):
        self.vectors = vectors
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        vectors = self.vectors
        if vectors and not isinstance(vectors[0], list):
            vectors = [vectors]
        return SimpleNamespace(data=[SimpleNamespace(embedding=vector) for vector in vectors])


class FakeOpenAIClient:
    def __init__(self, vector, *, error=None):
        self.embeddings = FakeEmbeddingsClient(vector, error=error)


def test_openai_embedding_provider_embeds_text_with_configured_model_and_dimensions():
    client = FakeOpenAIClient([0.1, 0.2, 0.3])
    provider = OpenAIEmbeddingProvider(
        client=client,
        model="text-embedding-3-small",
        dimensions=3,
    )

    result = provider.embed_text("Dataset: Tasks\nTitle: Add vector search")

    assert result == EmbeddingResult(
        vector=[0.1, 0.2, 0.3],
        model="text-embedding-3-small",
        dimensions=3,
    )
    assert client.embeddings.calls == [
        {
            "model": "text-embedding-3-small",
            "input": "Dataset: Tasks\nTitle: Add vector search",
            "dimensions": 3,
        }
    ]


def test_openai_embedding_provider_rejects_dimension_mismatch():
    provider = OpenAIEmbeddingProvider(
        client=FakeOpenAIClient([0.1, 0.2]),
        model="text-embedding-3-small",
        dimensions=3,
    )

    with pytest.raises(ValueError, match="Expected embedding with 3 dimensions"):
        provider.embed_text("short text")


def test_openai_embedding_provider_embeds_texts_in_one_request():
    client = FakeOpenAIClient([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
    provider = OpenAIEmbeddingProvider(
        client=client,
        model="text-embedding-3-small",
        dimensions=3,
    )

    results = provider.embed_texts(["first row", "second row"])

    assert results == [
        EmbeddingResult(
            vector=[0.1, 0.2, 0.3],
            model="text-embedding-3-small",
            dimensions=3,
        ),
        EmbeddingResult(
            vector=[0.4, 0.5, 0.6],
            model="text-embedding-3-small",
            dimensions=3,
        ),
    ]
    assert client.embeddings.calls == [
        {
            "model": "text-embedding-3-small",
            "input": ["first row", "second row"],
            "dimensions": 3,
        }
    ]


def test_openai_embedding_provider_wraps_openai_errors():
    provider = OpenAIEmbeddingProvider(
        client=FakeOpenAIClient([], error=OpenAIError("network unavailable")),
        model="text-embedding-3-small",
        dimensions=3,
    )

    with pytest.raises(EmbeddingProviderError, match="OpenAI embedding request failed"):
        provider.embed_text("short text")


def test_get_embedding_provider_requires_vector_search_feature_flag():
    with override_settings(ROWSET_VECTOR_SEARCH_ENABLED=False, OPENAI_API_KEY="sk-test"):
        with pytest.raises(ImproperlyConfigured, match="ROWSET_VECTOR_SEARCH_ENABLED"):
            get_embedding_provider()


def test_get_embedding_provider_requires_openai_api_key():
    with override_settings(ROWSET_VECTOR_SEARCH_ENABLED=True, OPENAI_API_KEY=""):
        with pytest.raises(ImproperlyConfigured, match="OPENAI_API_KEY"):
            get_embedding_provider()


def test_get_embedding_provider_reuses_configured_provider():
    with override_settings(
        ROWSET_VECTOR_SEARCH_ENABLED=True,
        OPENAI_API_KEY="sk-test-cache",
        ROWSET_EMBEDDING_MODEL="text-embedding-3-small",
        ROWSET_EMBEDDING_DIMENSIONS=3,
    ):
        first = get_embedding_provider()
        second = get_embedding_provider()

    assert first is second

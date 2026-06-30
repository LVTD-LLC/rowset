from types import SimpleNamespace

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from apps.datasets.embeddings import (
    EmbeddingResult,
    OpenAIEmbeddingProvider,
    get_embedding_provider,
)


class FakeEmbeddingsClient:
    def __init__(self, vector):
        self.vector = vector
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(embedding=self.vector)])


class FakeOpenAIClient:
    def __init__(self, vector):
        self.embeddings = FakeEmbeddingsClient(vector)


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


def test_get_embedding_provider_requires_openai_api_key():
    with override_settings(OPENAI_API_KEY=""):
        with pytest.raises(ImproperlyConfigured, match="OPENAI_API_KEY"):
            get_embedding_provider()

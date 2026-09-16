from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import tiktoken
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


class TokenLimitedEmbedder:
    """Reproduce the provider's real per-input limit without network requests."""

    def __init__(self):
        self.calls = []
        self.encoding = tiktoken.get_encoding("cl100k_base")

    def embed_documents_sync(self, documents):
        self.calls.append(list(documents))
        if any(len(self.encoding.encode_ordinary(text)) > 8192 for text in documents):
            raise ModelHTTPError(400, "text-embedding-3-small", body="maximum input length")
        # Different vectors make dropped chunks and incorrect row mapping observable.
        vectors = [[1.0, 0.0] if "TAIL" not in text else [0.0, 1.0] for text in documents]
        return SimpleNamespace(embeddings=vectors)

    def embed_query_sync(self, query):
        return self.embed_documents_sync([query])


@pytest.mark.parametrize("body", ["AGI " * 5000, "😀漢字" * 4000], ids=["ascii", "unicode"])
@pytest.mark.parametrize("model", ["openai/text-embedding-3-small", "text-embedding-3-small"])
def test_oversized_embedding_preserves_all_text_and_combines_chunks(body, model):
    text = body + "TAIL <|endoftext|>"
    embedder = TokenLimitedEmbedder()
    provider = OpenRouterPydanticAIEmbeddingProvider(embedder=embedder, model=model, dimensions=2)

    result = provider.embed_text(text)

    chunks = [chunk for batch in embedder.calls for chunk in batch]
    assert len(chunks) > 1
    assert "".join(chunks) == text
    assert all(len(embedder.encoding.encode_ordinary(chunk)) <= 8191 for chunk in chunks)
    weights = [len(embedder.encoding.encode_ordinary(chunk)) for chunk in chunks]
    expected = [sum(weights[:-1]), weights[-1]]
    norm = sum(value**2 for value in expected) ** 0.5
    assert result.vector == pytest.approx([value / norm for value in expected])


def test_embedding_batch_preserves_row_mapping_and_bounds_requests():
    embedder = TokenLimitedEmbedder()
    provider = OpenRouterPydanticAIEmbeddingProvider(
        embedder=embedder, model="openai/text-embedding-3-small", dimensions=2
    )
    texts = ["short"] * 33 + ["AGI " * 5000 + "TAIL", "TAIL"]

    results = provider.embed_texts(texts)

    assert len(results) == len(texts)
    assert all(result.vector == [1.0, 0.0] for result in results[:33])
    assert results[-2].vector[0] > 0
    assert results[-2].vector[1] > 0
    assert results[-1].vector == [0.0, 1.0]
    assert all(len(batch) <= 32 for batch in embedder.calls)
    assert "".join(chunk for batch in embedder.calls for chunk in batch) == "".join(texts)


def test_embedding_at_safe_token_boundary_is_unchanged():
    embedder = TokenLimitedEmbedder()
    text = "x " * 8190
    assert len(embedder.encoding.encode_ordinary(text)) == 8191
    provider = OpenRouterPydanticAIEmbeddingProvider(
        embedder=embedder, model="openai/text-embedding-3-small", dimensions=2
    )

    provider.embed_text(text)

    assert embedder.calls == [[text]]


def test_oversized_row_indexing_keeps_stored_data_and_upserts_one_vector():
    from apps.datasets.services import index_dataset_row_vector

    dataset = SimpleNamespace(
        name="Synthetic dataset",
        index_column="id",
        column_schema={},
        headers=["id", "body"],
        key="test-dataset",
        id=1,
        profile_id=1,
        archived_at=None,
    )
    data = {"id": "1", "body": "AGI " * 5000 + "TAIL"}
    row = SimpleNamespace(dataset=dataset, data=data.copy(), id=1, row_number=1, index_value="1")
    embedder = TokenLimitedEmbedder()
    provider = OpenRouterPydanticAIEmbeddingProvider(
        embedder=embedder, model="openai/text-embedding-3-small", dimensions=2
    )
    store = Mock()

    index_dataset_row_vector(row, embedding_provider=provider, vector_store=store)

    assert row.data == data
    store.upsert_dataset_row_vector.assert_called_once()
    assert store.upsert_dataset_row_vector.call_args.args[:2] == (dataset, row)
    assert all(value > 0 for value in store.upsert_dataset_row_vector.call_args.args[2])


def test_embedding_batch_rejects_missing_results_before_mapping_rows():
    provider = OpenRouterPydanticAIEmbeddingProvider(
        embedder=FakePydanticAIEmbedder([[1.0, 0.0]]),
        model="openai/text-embedding-3-small",
        dimensions=2,
    )
    with pytest.raises(EmbeddingProviderError, match="Expected 2 embeddings, got 1"):
        provider.embed_texts(["first", "second"])


def test_embedding_empty_batch_does_not_call_provider():
    embedder = TokenLimitedEmbedder()
    provider = OpenRouterPydanticAIEmbeddingProvider(
        embedder=embedder, model="openai/text-embedding-3-small", dimensions=2
    )
    assert provider.embed_texts([]) == []
    assert embedder.calls == []


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


def test_openrouter_embedding_provider_attributes_requests_to_rowset(monkeypatch):
    built_embedder = SimpleNamespace()

    def capture_embedder(model, *, settings):
        built_embedder.model = model
        built_embedder.settings = settings
        return built_embedder

    monkeypatch.setattr("apps.datasets.embeddings.Embedder", capture_embedder)

    with override_settings(SITE_URL="https://www.rowset.com"):
        provider = OpenRouterPydanticAIEmbeddingProvider(
            api_key="sk-test",
            base_url="https://openrouter.ai/api/v1",
        )

    assert provider.embedder is built_embedder
    assert built_embedder.settings["extra_headers"] == {
        "HTTP-Referer": "https://www.rowset.com",
        "X-OpenRouter-Title": "Rowset",
    }


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

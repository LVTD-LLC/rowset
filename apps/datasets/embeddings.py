from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from openai import OpenAI


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    model: str
    dimensions: int


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int

    def embed_text(self, text: str) -> EmbeddingResult: ...

    def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]: ...


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        *,
        client=None,
        model: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        self.model = model or settings.ROWSET_EMBEDDING_MODEL
        self.dimensions = dimensions or settings.ROWSET_EMBEDDING_DIMENSIONS
        self.client = client or OpenAI(api_key=settings.OPENAI_API_KEY)

    def embed_text(self, text: str) -> EmbeddingResult:
        return self._embed(text)[0]

    def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        if not texts:
            return []
        return self._embed(texts)

    def _embed(self, input_value: str | list[str]) -> list[EmbeddingResult]:
        response = self.client.embeddings.create(
            model=self.model,
            input=input_value,
            dimensions=self.dimensions,
        )
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


def get_embedding_provider() -> EmbeddingProvider:
    from apps.datasets.vector_search import qdrant_is_enabled

    if not qdrant_is_enabled():
        raise ImproperlyConfigured(
            "ROWSET_VECTOR_SEARCH_ENABLED must be true before embedding rows."
        )
    if not str(settings.OPENAI_API_KEY or "").strip():
        raise ImproperlyConfigured("OPENAI_API_KEY must be configured before embedding rows.")
    return OpenAIEmbeddingProvider()

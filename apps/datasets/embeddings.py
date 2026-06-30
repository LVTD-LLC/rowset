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
        response = self.client.embeddings.create(
            model=self.model,
            input=text,
            dimensions=self.dimensions,
        )
        vector = list(response.data[0].embedding)
        if len(vector) != self.dimensions:
            raise ValueError(
                f"Expected embedding with {self.dimensions} dimensions, got {len(vector)}."
            )
        return EmbeddingResult(
            vector=vector,
            model=self.model,
            dimensions=self.dimensions,
        )


def get_embedding_provider() -> EmbeddingProvider:
    if not str(settings.OPENAI_API_KEY or "").strip():
        raise ImproperlyConfigured("OPENAI_API_KEY must be configured before embedding rows.")
    return OpenAIEmbeddingProvider()

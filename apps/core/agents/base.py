from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PydanticAIModelSpec:
    provider: str
    label: str


def build_model(*, provider: str, label: str):
    raise RuntimeError(
        "apps.core.agents.base.build_model was removed with the generic multi-provider "
        "agent factory. Use task-specific provider integrations instead; dataset vector "
        "embeddings use apps.datasets.embeddings.get_embedding_provider()."
    )

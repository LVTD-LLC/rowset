from typing import Any

from apps.core.models import AgentApiKey
from apps.datasets.choices import DatasetMutationType
from apps.datasets.models import Dataset, DatasetMutation


def actor_label_for(agent_api_key: AgentApiKey | None) -> str:
    if agent_api_key is None:
        return "Account"
    return agent_api_key.name


def record_dataset_mutation(
    dataset: Dataset,
    mutation_type: DatasetMutationType,
    summary: str,
    *,
    agent_api_key: AgentApiKey | None = None,
    target_type: str = "",
    target_identifier: str = "",
    metadata: dict[str, Any] | None = None,
) -> DatasetMutation:
    return DatasetMutation.objects.create(
        dataset=dataset,
        profile=dataset.profile,
        agent_api_key=agent_api_key,
        actor_label=actor_label_for(agent_api_key),
        mutation_type=mutation_type,
        summary=summary,
        target_type=target_type,
        target_identifier=str(target_identifier or ""),
        metadata=metadata or {},
    )

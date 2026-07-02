from typing import Any

from apps.core.models import AgentApiKey
from apps.datasets.choices import DatasetMutationType
from apps.datasets.model_typing import dataset_mutation_objects
from apps.datasets.models import Dataset, DatasetMutation, agent_actor_label


def record_dataset_mutation(
    dataset: Dataset,
    mutation_type: DatasetMutationType,
    summary: str,
    *,
    agent_api_key: AgentApiKey | None = None,
    target_type: str = "",
    target_identifier: str | int | None = "",
    metadata: dict[str, Any] | None = None,
) -> DatasetMutation:
    return dataset_mutation_objects().create(
        dataset=dataset,
        profile=dataset.profile,
        agent_api_key=agent_api_key,
        actor_label=agent_actor_label(agent_api_key),
        mutation_type=mutation_type,
        summary=summary,
        target_type=target_type,
        target_identifier="" if target_identifier is None else str(target_identifier),
        metadata=metadata or {},
    )

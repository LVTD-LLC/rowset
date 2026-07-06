from django.db import models
from django.urls import reverse

from apps.core.base_models import BaseModel
from apps.core.models import AgentApiKey, Profile
from apps.datasets.models import Dataset


class DatasetPluginActivation(BaseModel):
    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="dataset_plugin_activations",
    )
    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        related_name="plugin_activations",
    )
    created_by_agent_api_key = models.ForeignKey(
        AgentApiKey,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_dataset_plugin_activations",
    )
    updated_by_agent_api_key = models.ForeignKey(
        AgentApiKey,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_dataset_plugin_activations",
    )
    plugin_slug = models.CharField(max_length=80)
    enabled = models.BooleanField(default=True)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["dataset__name", "plugin_slug", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "plugin_slug"],
                name="unique_dataset_plugin_activation",
            ),
        ]
        indexes = [
            models.Index(fields=["profile", "dataset"], name="dataset_plugin_owner_idx"),
            models.Index(fields=["plugin_slug", "enabled"], name="dataset_plugin_enabled_idx"),
        ]

    def __str__(self):
        return f"{self.dataset_id} {self.plugin_slug}"

    def get_absolute_url(self):
        return reverse(
            "dataset_plugin_detail",
            kwargs={"dataset_key": self.dataset.key, "plugin_slug": self.plugin_slug},
        )

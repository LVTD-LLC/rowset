from apps.dataset_plugins.registry import (
    DatasetPluginColumnRole,
    DatasetPluginSpec,
    register_dataset_plugin,
)

register_dataset_plugin(
    DatasetPluginSpec(
        slug="flashcards",
        name="Flashcards",
        description=(
            "Render dataset rows as study cards with front and back fields. "
            "Agents keep the rows current; Rowset provides the review surface."
        ),
        view_template_name="dataset_plugins/flashcards.html",
        column_roles=(
            DatasetPluginColumnRole(
                key="front_title",
                label="Front title",
                description="Optional short heading shown above the front prompt.",
                required=False,
                aliases=("front_title", "front title", "title", "term"),
            ),
            DatasetPluginColumnRole(
                key="front_question",
                label="Front question",
                description="Required prompt shown before the card is flipped.",
                aliases=("front_question", "front question", "question", "front", "q", "prompt"),
            ),
            DatasetPluginColumnRole(
                key="front_image",
                label="Front image",
                description="Optional image shown on the front of the card.",
                required=False,
                aliases=("front_image", "front image", "question_image", "prompt_image"),
            ),
            DatasetPluginColumnRole(
                key="back_title",
                label="Back title",
                description="Optional short heading shown above the answer.",
                required=False,
                aliases=("back_title", "back title", "answer_title"),
            ),
            DatasetPluginColumnRole(
                key="back_answer",
                label="Back answer",
                description="Required answer shown after the card is flipped.",
                aliases=("back_answer", "back answer", "answer", "back", "a", "response"),
            ),
            DatasetPluginColumnRole(
                key="back_image",
                label="Back image",
                description="Optional image shown on the back of the card.",
                required=False,
                aliases=("back_image", "back image", "answer_image"),
            ),
            DatasetPluginColumnRole(
                key="tags",
                label="Tags",
                description="Optional tags or grouping text for filtering outside the card view.",
                required=False,
                aliases=("tags", "tag", "labels", "category"),
            ),
        ),
    )
)

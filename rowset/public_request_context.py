from typing import Literal, get_args

PublicDatasetContentSurface = Literal["preview", "row_detail", "markdown", "export"]

PUBLIC_DATASET_CONTENT_SURFACES = frozenset(get_args(PublicDatasetContentSurface))

from typing import Protocol, cast

from apps.pages.models import ReferrerBanner


def _django_attr(model: object, name: str) -> object:
    return getattr(model, name)


class ReferrerBannerQuerySet(Protocol):
    def filter(self, **filters: object) -> ReferrerBannerQuerySet: ...

    def first(self) -> ReferrerBanner | None: ...


class ReferrerBannerManager(Protocol):
    def filter(self, **filters: object) -> ReferrerBannerQuerySet: ...

    def get(self, **filters: object) -> ReferrerBanner: ...


ReferrerBannerDoesNotExist = cast(
    type[Exception],
    _django_attr(ReferrerBanner, "DoesNotExist"),
)
ReferrerBannerMultipleObjectsReturned = cast(
    type[Exception],
    _django_attr(ReferrerBanner, "MultipleObjectsReturned"),
)


def referrer_banner_objects() -> ReferrerBannerManager:
    return cast(ReferrerBannerManager, _django_attr(ReferrerBanner, "objects"))

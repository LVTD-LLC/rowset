from django.core import signing

SMOKE_HEADER = "X-Rowset-Post-Deploy-Smoke"
SMOKE_SIGNING_SALT = "rowset.post-deploy-smoke"


def create_smoke_token(marker: str) -> str:
    return signing.dumps(marker, salt=SMOKE_SIGNING_SALT)


def read_smoke_token(token: str) -> str | None:
    try:
        marker = signing.loads(token, salt=SMOKE_SIGNING_SALT)
    except signing.BadSignature:
        return None
    return marker if isinstance(marker, str) and marker else None

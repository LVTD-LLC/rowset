import structlog


def get_filebridge_logger(name):
    """This will add a `filebridge` prefix to logger for easy configuration."""

    return structlog.get_logger(
        f"filebridge.{name}",
        project="filebridge"
    )

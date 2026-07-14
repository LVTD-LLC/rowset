from __future__ import annotations

import platform
import sys


def verify_runtime_platform(expected_machine: str) -> None:
    actual_machine = platform.machine()
    if actual_machine != expected_machine:
        raise RuntimeError(f"Expected {expected_machine}, got {actual_machine}")


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} EXPECTED_MACHINE", file=sys.stderr)
        return 2

    import django  # noqa: F401

    import deployment.healthcheck  # noqa: F401
    import rowset  # noqa: F401

    try:
        verify_runtime_platform(sys.argv[1])
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

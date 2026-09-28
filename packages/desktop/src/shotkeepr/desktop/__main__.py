"""Punto di ingresso dell'applicazione desktop (`shotkeepr`)."""

from __future__ import annotations

from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

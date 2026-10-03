from enum import StrEnum


class ExclusionReason(StrEnum):
    CORRUPTED = "CORRUPTED"
    UNREADABLE = "UNREADABLE"
    UNSUPPORTED = "UNSUPPORTED"

    def __str__(self) -> str:
        return str(self.value)

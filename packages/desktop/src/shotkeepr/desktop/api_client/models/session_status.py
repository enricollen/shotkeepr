from enum import StrEnum


class SessionStatus(StrEnum):
    ANALYZED = "ANALYZED"
    ANALYZING = "ANALYZING"
    CANCELLED = "CANCELLED"
    CREATED = "CREATED"
    FAILED = "FAILED"
    IMPORTED = "IMPORTED"
    IMPORTING = "IMPORTING"
    PAUSED = "PAUSED"

    def __str__(self) -> str:
        return str(self.value)

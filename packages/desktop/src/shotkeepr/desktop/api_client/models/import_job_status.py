from enum import StrEnum


class ImportJobStatus(StrEnum):
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"

    def __str__(self) -> str:
        return str(self.value)

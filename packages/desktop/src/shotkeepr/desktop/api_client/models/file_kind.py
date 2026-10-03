from enum import StrEnum


class FileKind(StrEnum):
    RAW = "RAW"
    STANDARD = "STANDARD"

    def __str__(self) -> str:
        return str(self.value)

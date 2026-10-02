from enum import StrEnum


class Theme(StrEnum):
    DARK = "DARK"
    LIGHT = "LIGHT"

    def __str__(self) -> str:
        return str(self.value)

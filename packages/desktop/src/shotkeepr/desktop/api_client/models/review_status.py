from enum import StrEnum


class ReviewStatus(StrEnum):
    KEEP = "KEEP"
    REJECT = "REJECT"
    REVIEW = "REVIEW"

    def __str__(self) -> str:
        return str(self.value)

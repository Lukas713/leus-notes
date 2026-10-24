from __future__ import annotations

import re
from dataclasses import dataclass

PATTERN = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$")


class PeopleCountError(ValueError):
    pass


@dataclass(frozen=True)
class PeopleCount:
    minimum: int | None = None
    maximum: int | None = None

    @classmethod
    def parse(cls, text: str | int | None) -> PeopleCount:
        text = "" if text is None else str(text).strip()
        if text.lower() in ("", "auto"):
            return cls()
        match = PATTERN.match(text)
        if not match:
            raise PeopleCountError(f"'{text}' is not a number of people. Use a number like 3, a range like 3-5, or auto.")
        low = int(match[1])
        high = int(match[2] or low)
        if low < 2:
            raise PeopleCountError("A call needs at least 2 people: you and someone else.")
        if high < low:
            raise PeopleCountError(f"'{text}' is not a valid range.")
        return cls(low, high)

    @property
    def is_auto(self) -> bool:
        return self.minimum is None

    @property
    def is_exact(self) -> bool:
        return not self.is_auto and self.minimum == self.maximum

    def needs_speaker_separation(self) -> bool:
        return not (self.is_exact and self.minimum == 2)

    def diarization_options(self) -> dict[str, int]:
        if self.minimum is None or self.maximum is None:
            return {}
        if self.is_exact:
            return {"num_speakers": self.minimum - 1}
        return {"min_speakers": self.minimum - 1, "max_speakers": self.maximum - 1}

    def __str__(self) -> str:
        if self.is_auto:
            return "auto"
        if self.is_exact:
            return str(self.minimum)
        return f"{self.minimum}-{self.maximum}"

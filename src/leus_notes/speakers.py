from __future__ import annotations

import json
from bisect import bisect_left
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from .diarizer import Turn
from .meeting import write_json
from .transcriber import Segment, Word

ME = "me"
THEM = "them"
CARRY_NAME_SHARE = 0.5


@dataclass(frozen=True)
class Utterance:
    start: float
    end: float
    speaker: str
    text: str


def save_utterances(path: Path, utterances: Iterable[Utterance]) -> None:
    write_json(path, {"utterances": [asdict(utterance) for utterance in utterances]})


def load_utterances(path: Path) -> list[Utterance]:
    return [Utterance(**item) for item in json.loads(path.read_text())["utterances"]]


def single_speaker(segments: Iterable[Segment], speaker: str) -> list[Utterance]:
    return [Utterance(segment.start, segment.end, speaker, segment.text) for segment in segments]


class TurnIndex:
    def __init__(self, turns: Sequence[Turn]):
        self.turns = sorted(turns, key=lambda turn: turn.start)
        self.starts = [turn.start for turn in self.turns]
        self.longest = max((turn.end - turn.start for turn in self.turns), default=0.0)

    def speaker_at(self, start: float, end: float) -> str:
        best_speaker, best_overlap = None, 0.0
        first = bisect_left(self.starts, start - self.longest)
        for turn in self.turns[first:]:
            if turn.start >= end:
                break
            overlap = min(end, turn.end) - max(start, turn.start)
            if overlap > best_overlap:
                best_speaker, best_overlap = turn.speaker, overlap
        if best_speaker is not None:
            return best_speaker
        middle = (start + end) / 2
        return min(self.turns, key=lambda turn: distance(middle, turn)).speaker


def distance(point: float, turn: Turn) -> float:
    if turn.start <= point <= turn.end:
        return 0.0
    return min(abs(point - turn.start), abs(point - turn.end))


def split_by_turns(segments: Iterable[Segment], turns: Sequence[Turn]) -> list[Utterance]:
    index = TurnIndex(turns)
    utterances: list[Utterance] = []
    for segment in segments:
        run: list[Word] = []
        run_speaker = None
        for word in segment.words or (Word(segment.start, segment.end, segment.text),):
            speaker = index.speaker_at(word.start, word.end)
            if run and speaker != run_speaker:
                utterances.append(from_words(run, run_speaker))
                run = []
            run.append(word)
            run_speaker = speaker
        if run:
            utterances.append(from_words(run, run_speaker))
    return utterances


def from_words(words: Sequence[Word], speaker: str) -> Utterance:
    return Utterance(words[0].start, words[-1].end, speaker, "".join(word.text for word in words).strip())


def renumber(utterances: Iterable[Utterance]) -> list[Utterance]:
    ordered = sorted(utterances, key=lambda utterance: utterance.start)
    numbers: dict[str, str] = {}
    for utterance in ordered:
        if utterance.speaker not in (ME, THEM) and utterance.speaker not in numbers:
            numbers[utterance.speaker] = str(len(numbers) + 1)
    return [
        Utterance(utterance.start, utterance.end, numbers.get(utterance.speaker, utterance.speaker), utterance.text)
        for utterance in ordered
    ]


def speaker_ids(utterances: Iterable[Utterance]) -> list[str]:
    seen: list[str] = []
    for utterance in sorted(utterances, key=lambda utterance: utterance.start):
        if utterance.speaker not in (ME, THEM) and utterance.speaker not in seen:
            seen.append(utterance.speaker)
    return seen


def carry_names(old: Sequence[Utterance], new: Sequence[Utterance], names: dict[str, str]) -> dict[str, str]:
    named_old = [utterance for utterance in old if utterance.speaker in names]
    carried: dict[str, str] = {}
    for speaker in speaker_ids(new):
        spoken = [utterance for utterance in new if utterance.speaker == speaker]
        total = sum(utterance.end - utterance.start for utterance in spoken)
        shared: dict[str, float] = {}
        for mine in spoken:
            for theirs in named_old:
                overlap = min(mine.end, theirs.end) - max(mine.start, theirs.start)
                if overlap > 0:
                    name = names[theirs.speaker]
                    shared[name] = shared.get(name, 0.0) + overlap
        if total > 0 and shared:
            best = max(shared, key=shared.__getitem__)
            if shared[best] / total >= CARRY_NAME_SHARE:
                carried[speaker] = best
    return carried

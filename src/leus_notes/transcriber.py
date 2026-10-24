from __future__ import annotations

import gc
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

SAMPLE_RATE = 16000
PAUSE_SECONDS = 1.0
GROUP_SPEECH_SECONDS = 30.0

Clip = tuple[float, float]


class AudioError(Exception):
    pass


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str
    words: tuple[Word, ...] = ()


@dataclass(frozen=True)
class ChannelTranscript:
    languages: tuple[str, ...]
    duration: float
    segments: tuple[Segment, ...]

    def to_dict(self) -> dict:
        return {
            "languages": list(self.languages),
            "duration": self.duration,
            "segments": [
                {
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                    "words": [[word.start, word.end, word.text] for word in segment.words],
                }
                for segment in self.segments
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ChannelTranscript:
        return cls(
            languages=tuple(data["languages"]),
            duration=data["duration"],
            segments=tuple(
                Segment(
                    start=segment["start"],
                    end=segment["end"],
                    text=segment["text"],
                    words=tuple(Word(start, end, text) for start, end, text in segment["words"]),
                )
                for segment in data["segments"]
            ),
        )


def load_audio(path: Path):
    import numpy

    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"],
        capture_output=True,
    )
    if result.returncode != 0:
        raise AudioError(f"ffmpeg could not read {path}: {result.stderr.decode(errors='replace').strip()}")
    return numpy.frombuffer(result.stdout, dtype=numpy.float32).copy()


def speech_clips(audio) -> list[Clip]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    regions = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=500, speech_pad_ms=200))
    return merge_regions([(region["start"] / SAMPLE_RATE, region["end"] / SAMPLE_RATE) for region in regions])


def merge_regions(regions: list[Clip], gap_seconds: float = PAUSE_SECONDS) -> list[Clip]:
    merged: list[Clip] = []
    for start, end in regions:
        if merged and start - merged[-1][1] <= gap_seconds:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def group_clips(clips: list[Clip], speech_seconds: float = GROUP_SPEECH_SECONDS) -> list[list[Clip]]:
    groups: list[list[Clip]] = []
    spoken = 0.0
    for clip in clips:
        if not groups or spoken >= speech_seconds:
            groups.append([])
            spoken = 0.0
        groups[-1].append(clip)
        spoken += clip[1] - clip[0]
    return groups


def split_on_pauses(segment: Segment, pause_seconds: float = PAUSE_SECONDS) -> list[Segment]:
    if not segment.words:
        return [segment]
    groups: list[list[Word]] = [[segment.words[0]]]
    for previous, word in zip(segment.words, segment.words[1:]):
        if word.start - previous.end > pause_seconds:
            groups.append([])
        groups[-1].append(word)
    return [
        Segment(group[0].start, group[-1].end, "".join(word.text for word in group).strip(), tuple(group))
        for group in groups
    ]


def shifted(segment, offset: float) -> Segment:
    words = tuple(Word(word.start + offset, word.end + offset, word.word) for word in segment.words or ())
    return Segment(segment.start + offset, segment.end + offset, segment.text.strip(), words)


def resolve_device(device: str) -> tuple[str, str]:
    if device == "auto":
        import ctranslate2

        device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    return device, "float16" if device == "cuda" else "int8"


class Transcriber:
    def __init__(self, model_name: str, device: str, download_root: Path, language: str, languages: tuple[str, ...]):
        from faster_whisper import WhisperModel

        self.device, compute_type = resolve_device(device)
        self.language = language
        self.languages = languages
        self.model = WhisperModel(model_name, device=self.device, compute_type=compute_type, download_root=str(download_root))

    def transcribe(self, audio_path: Path, *, progress: Callable[[float], None] | None = None) -> ChannelTranscript:
        audio = load_audio(audio_path)
        duration = len(audio) / SAMPLE_RATE
        segments: list[Segment] = []
        spoken: dict[str, float] = {}
        for group in group_clips(speech_clips(audio)):
            offset = group[0][0]
            piece = audio[int(offset * SAMPLE_RATE) : int(group[-1][1] * SAMPLE_RATE)]
            language = self.pick_language(audio, group)
            spoken[language] = spoken.get(language, 0.0) + sum(end - start for start, end in group)
            results, _ = self.model.transcribe(
                piece,
                language=language,
                beam_size=5,
                vad_filter=False,
                clip_timestamps=[moment - offset for clip in group for moment in clip],
                condition_on_previous_text=False,
                word_timestamps=True,
            )
            for result in results:
                if progress and duration:
                    progress(min((result.end + offset) / duration, 1.0))
                if result.text.strip():
                    segments += split_on_pauses(shifted(result, offset))
        languages = tuple(sorted(spoken, key=spoken.__getitem__, reverse=True))
        return ChannelTranscript(languages, duration, tuple(segments))

    def pick_language(self, audio, group: list[Clip]) -> str:
        if self.language != "auto":
            return self.language
        import numpy

        sample = numpy.concatenate([audio[int(start * SAMPLE_RATE) : int(end * SAMPLE_RATE)] for start, end in group])
        _, _, probabilities = self.model.detect_language(sample[: int(GROUP_SPEECH_SECONDS * SAMPLE_RATE)])
        allowed = {language: probability for language, probability in probabilities if language in self.languages}
        return max(allowed, key=allowed.__getitem__) if allowed else self.languages[0]

    def self_test(self) -> None:
        import numpy

        segments, _ = self.model.transcribe(numpy.zeros(SAMPLE_RATE, dtype=numpy.float32), language=self.languages[0])
        list(segments)

    def close(self) -> None:
        del self.model
        gc.collect()

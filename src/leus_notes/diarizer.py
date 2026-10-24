from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .transcriber import SAMPLE_RATE, load_audio


class DiarizationError(Exception):
    pass


@dataclass(frozen=True)
class Turn:
    start: float
    end: float
    speaker: str


def load_pipeline(model: str, token: str | None):
    if not token:
        raise DiarizationError("no Hugging Face token is configured (HF_TOKEN in .env)")
    import torch
    from pyannote.audio import Pipeline

    try:
        pipeline = Pipeline.from_pretrained(model, token=token)
    except Exception as error:
        raise DiarizationError(
            f"could not load {model} ({type(error).__name__}: {error}). "
            f"Check the token and accept the model's conditions at https://huggingface.co/{model}"
        ) from error
    if pipeline is None:
        raise DiarizationError(f"could not load {model}. Accept its conditions at https://huggingface.co/{model}")
    if torch.cuda.is_available():
        pipeline.to(torch.device("cuda"))
    return pipeline


def diarize(pipeline, audio_path: Path, options: dict[str, int]) -> list[Turn]:
    import torch

    waveform = torch.from_numpy(load_audio(audio_path)).unsqueeze(0)
    output = pipeline({"waveform": waveform, "sample_rate": SAMPLE_RATE}, **options)
    annotation = getattr(output, "exclusive_speaker_diarization", None)
    if annotation is None:
        annotation = getattr(output, "speaker_diarization", output)
    return [Turn(segment.start, segment.end, str(label)) for segment, _, label in annotation.itertracks(yield_label=True)]

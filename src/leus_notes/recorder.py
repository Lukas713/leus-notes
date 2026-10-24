from __future__ import annotations

import ctypes
import math
import signal
import subprocess
import threading
import time
from array import array
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import BinaryIO

PR_SET_PDEATHSIG = 1
SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2


class RecordingError(Exception):
    pass


class StopReason(Enum):
    INTERRUPTED = "interrupted"
    STOP_COMMAND = "stop-command"
    SILENCE = "silence"


@dataclass(frozen=True)
class Devices:
    mic: str
    monitors: tuple[str, ...]


@dataclass(frozen=True)
class RecordingResult:
    reason: StopReason
    seconds: float


def default_devices(all_outputs: bool = True) -> Devices:
    default_sink = pactl("get-default-sink")
    sinks = [line.split("\t")[1] for line in pactl("list", "short", "sinks").splitlines() if "\t" in line] if all_outputs else []
    ordered = [default_sink, *(sink for sink in sinks if sink != default_sink)]
    return Devices(mic=pactl("get-default-source"), monitors=tuple(f"{sink}.monitor" for sink in ordered))


def pactl(*arguments: str) -> str:
    command = " ".join(arguments)
    try:
        result = subprocess.run(["pactl", *arguments], capture_output=True, text=True, check=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as error:
        raise RecordingError(f"Could not ask PipeWire for the audio devices (pactl {command}): {error}") from error
    output = result.stdout.strip()
    if not output:
        raise RecordingError(f"PipeWire returned nothing for 'pactl {command}'.")
    return output


def ffmpeg_command(devices: Devices, me_path: Path, them_path: Path, *, level_tap: bool = False) -> list[str]:
    command = ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-y"]
    sources = [(devices.mic, "microphone"), *((monitor, "call audio") for monitor in devices.monitors)]
    for device, stream_name in sources:
        command += [
            "-f", "pulse",
            "-name", "leus-notes",
            "-stream_name", stream_name,
            "-sample_rate", str(SAMPLE_RATE),
            "-channels", "1",
            "-i", device,
        ]
    monitors = "".join(f"[{index}:a]" for index in range(1, len(sources)))
    call = f"{monitors}amix=inputs={len(devices.monitors)}:normalize=0" if len(devices.monitors) > 1 else f"{monitors}anull"
    if not level_tap:
        return command + [
            "-filter_complex", f"{call}[them]",
            "-map", "0:a", "-c:a", "flac", str(me_path),
            "-map", "[them]", "-c:a", "flac", str(them_path),
        ]
    return command + [
        "-filter_complex", f"[0:a]asplit=2[me][mic];{call},asplit=2[them][call];[mic][call]amix=inputs=2:normalize=0[level]",
        "-map", "[me]", "-c:a", "flac", str(me_path),
        "-map", "[them]", "-c:a", "flac", str(them_path),
        "-map", "[level]", "-f", "s16le", "pipe:1",
    ]


def record(
    devices: Devices,
    me_path: Path,
    them_path: Path,
    *,
    silence_seconds: float = 0,
    silence_threshold_db: float = -35,
) -> RecordingResult:
    reasons: list[StopReason] = []
    wake = threading.Event()

    def request_stop(reason: StopReason) -> None:
        if not reasons:
            reasons.append(reason)
        wake.set()

    previous_interrupt = signal.signal(signal.SIGINT, lambda *_: request_stop(StopReason.INTERRUPTED))
    previous_terminate = signal.signal(signal.SIGTERM, lambda *_: request_stop(StopReason.STOP_COMMAND))
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            ffmpeg_command(devices, me_path, them_path, level_tap=bool(silence_seconds)),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE if silence_seconds else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
            preexec_fn=stop_with_parent,
        )
        log_tail: deque[str] = deque(maxlen=20)
        watchers = [threading.Thread(target=watch_log, args=(process.stderr, log_tail), daemon=True)]
        if silence_seconds:
            watchers.append(
                threading.Thread(
                    target=watch_level,
                    args=(process.stdout, silence_seconds, silence_threshold_db, lambda: request_stop(StopReason.SILENCE)),
                    daemon=True,
                )
            )
        for watcher in watchers:
            watcher.start()
        while not wake.wait(0.5):
            if process.poll() is not None:
                watchers[0].join(timeout=2)
                raise RecordingError("ffmpeg stopped unexpectedly:\n" + "\n".join(log_tail))
        finish(process)
        for watcher in watchers:
            watcher.join(timeout=5)
    finally:
        signal.signal(signal.SIGINT, previous_interrupt)
        signal.signal(signal.SIGTERM, previous_terminate)
    return RecordingResult(reasons[0], time.monotonic() - started)


def stop_with_parent() -> None:
    ctypes.CDLL(None, use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGTERM)


def watch_log(stream: Iterable[bytes], tail: deque[str]) -> None:
    for line in stream:
        text = line.decode(errors="replace").rstrip()
        if text:
            tail.append(text)


def rms_dbfs(chunk: bytes) -> float:
    samples = array("h", chunk[: len(chunk) // 2 * 2])
    if not samples:
        return -math.inf
    mean_square = sum(sample * sample for sample in samples) / len(samples)
    return 10 * math.log10(mean_square / 32768**2) if mean_square else -math.inf


def watch_level(stream: BinaryIO, limit_seconds: float, threshold_db: float, on_silence: Callable[[], None]) -> None:
    quiet_seconds = 0
    while chunk := stream.read(BYTES_PER_SECOND):
        quiet_seconds = quiet_seconds + 1 if rms_dbfs(chunk) < threshold_db else 0
        if quiet_seconds >= limit_seconds:
            on_silence()


def finish(process: subprocess.Popen) -> None:
    try:
        process.stdin.write(b"q")
        process.stdin.close()
    except OSError:
        pass
    for escalation, timeout in ((None, 10), (signal.SIGINT, 5), (signal.SIGKILL, 5)):
        if escalation is not None:
            process.send_signal(escalation)
        try:
            process.wait(timeout=timeout)
            return
        except subprocess.TimeoutExpired:
            continue

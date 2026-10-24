import io
import math
from array import array
from collections import deque
from pathlib import Path

from leus_notes.recorder import BYTES_PER_SECOND, Devices, ffmpeg_command, rms_dbfs, watch_level, watch_log

ONE_OUTPUT = Devices(mic="alsa_input.usb-mic", monitors=("alsa_output.usb-headset.monitor",))
THREE_OUTPUTS = Devices(
    mic="alsa_input.usb-mic",
    monitors=("alsa_output.hdmi.monitor", "alsa_output.usb-headset.monitor", "alsa_output.pci.monitor"),
)


def inputs(command):
    return [command[index + 1] for index, part in enumerate(command) if part == "-i"]


def test_command_records_mic_and_every_output_as_mono_16k():
    command = ffmpeg_command(THREE_OUTPUTS, Path("/m/me.flac"), Path("/m/them.flac"))
    assert inputs(command) == [THREE_OUTPUTS.mic, *THREE_OUTPUTS.monitors]
    assert command.count("16000") == 4
    assert command[command.index("-filter_complex") + 1] == "[1:a][2:a][3:a]amix=inputs=3:normalize=0[them]"
    assert command[-10:] == ["-map", "0:a", "-c:a", "flac", "/m/me.flac", "-map", "[them]", "-c:a", "flac", "/m/them.flac"]


def test_command_with_a_single_output_passes_it_through():
    command = ffmpeg_command(ONE_OUTPUT, Path("/m/me.flac"), Path("/m/them.flac"))
    assert command[command.index("-filter_complex") + 1] == "[1:a]anull[them]"


def test_command_with_level_tap_streams_the_mix_to_stdout():
    command = ffmpeg_command(THREE_OUTPUTS, Path("/m/me.flac"), Path("/m/them.flac"), level_tap=True)
    graph = command[command.index("-filter_complex") + 1]
    assert graph.startswith("[0:a]asplit=2[me][mic];[1:a][2:a][3:a]amix=inputs=3:normalize=0,asplit=2[them][call];")
    assert graph.endswith("[mic][call]amix=inputs=2:normalize=0[level]")
    assert command[-5:] == ["-map", "[level]", "-f", "s16le", "pipe:1"]


def tone(amplitude, seconds=1):
    return array("h", [amplitude if index % 2 else -amplitude for index in range(16000 * seconds)]).tobytes()


def test_rms_dbfs():
    assert rms_dbfs(b"") == -math.inf
    assert rms_dbfs(tone(0)) == -math.inf
    assert round(rms_dbfs(tone(32767))) == 0
    assert round(rms_dbfs(tone(328))) == -40


def test_watch_level_fires_after_enough_quiet_seconds():
    loud, quiet = tone(10000), tone(100)
    fired = []
    watch_level(io.BytesIO(quiet * 2 + loud + quiet * 3), 3, -35, lambda: fired.append(1))
    assert fired == [1]
    fired.clear()
    watch_level(io.BytesIO(quiet * 2 + loud + quiet * 2), 3, -35, lambda: fired.append(1))
    assert fired == []
    assert len(tone(1)) == BYTES_PER_SECOND


def test_watch_log_keeps_the_last_lines():
    tail = deque(maxlen=2)
    watch_log([b"Input #0\n", b"\n", b"error A\n", b"error B\n"], tail)
    assert list(tail) == ["error A", "error B"]

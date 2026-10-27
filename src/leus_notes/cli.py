from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import control, doctor, recorder, sharing
from .config import ConfigError, Settings, load_settings
from .meeting import Meeting, MeetingNotFound, find_meeting, now, sweep_audio
from .notes import NotesError
from .people import PeopleCount, PeopleCountError
from .pipeline import Engine, PipelineError, process
from .recorder import RecordingError, RecordingResult, StopReason
from .sharing import SharingError
from .speakers import THEM, Utterance, load_utterances, speaker_ids
from .transcript import format_duration, format_timestamp

ASSIGNMENT = re.compile(r"^\s*(?:speaker\s*)?(\d+)\s*=(.*)$", re.IGNORECASE)
SAMPLE_LINES = 3
SAMPLE_WIDTH = 110


class UserError(Exception):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="leus-notes",
        description="Record a call on this computer and turn it into English meeting notes.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    people_help = "everyone who speaks in the call, including you: 3, a range like 3-5, or auto"

    start = commands.add_parser("start", help="start recording a call")
    start.add_argument("title", nargs="?", default="Meeting")
    start.add_argument("--number-of-people", metavar="N", help=people_help)
    start.set_defaults(handler=start_command)

    stop = commands.add_parser("stop", help="stop the running recording")
    stop.add_argument("--number-of-people", metavar="N", help=people_help)
    stop.set_defaults(handler=stop_command)

    status = commands.add_parser("status", help="show whether a recording is running")
    status.set_defaults(handler=status_command)

    process_parser = commands.add_parser("process", help="(re)process a meeting, latest by default")
    process_parser.add_argument("meeting", nargs="?", help="meeting folder or folder name")
    process_parser.add_argument("--redo-speakers", action="store_true", help="separate speakers again (needs the audio)")
    process_parser.add_argument("--number-of-people", metavar="N", help=people_help)
    process_parser.add_argument("--notes", action="store_true", help="rewrite the notes")
    process_parser.set_defaults(handler=process_command)

    names = commands.add_parser("names", help="assign names to speakers, latest meeting by default")
    names.add_argument("items", nargs="*", metavar="[meeting] [\"Speaker 1=Name\" ...]")
    names.set_defaults(handler=names_command)

    share = commands.add_parser("share", help="upload a meeting's notes as a Google Doc, latest meeting by default")
    share.add_argument("meeting", nargs="?", help="meeting folder or folder name")
    share.set_defaults(handler=share_command)

    doctor_parser = commands.add_parser("doctor", help="check the setup")
    doctor_parser.add_argument("--download-models", action="store_true", help="download and test the models")
    doctor_parser.set_defaults(handler=doctor_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings()
        for meeting in sweep_audio(settings.meetings_dir, settings.keep_audio_days, now()):
            print(f"Deleted old audio of {meeting.folder.name} (audio.keep_days = {settings.keep_audio_days}).")
        return args.handler(args, settings)
    except (ConfigError, PeopleCountError, MeetingNotFound, RecordingError, SharingError, UserError) as error:
        print(f"leus-notes: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


def start_command(args: argparse.Namespace, settings: Settings) -> int:
    people = PeopleCount.parse(args.number_of_people)
    active = control.read_active(settings.run_dir)
    if active:
        raise UserError(f"already recording '{active.title}'. Run `leus-notes stop` first.")
    devices = recorder.default_devices(all_outputs=settings.call_outputs == "all")
    meeting = Meeting.create(
        settings.meetings_dir, args.title, now(), str(people), {"mic": devices.mic, "call": " + ".join(devices.monitors)}
    )
    control.write_active(
        settings.run_dir,
        control.ActiveRecording(
            pid=os.getpid(),
            folder=str(meeting.folder),
            title=meeting.title,
            started_at=meeting.started_at.isoformat(),
            people=str(people),
        ),
    )
    print(f"Recording '{meeting.title}' into {meeting.folder}")
    print(f"  mic:        {devices.mic}")
    print(f"  call audio: {describe_outputs(devices)}")
    if settings.auto_stop_silence_minutes:
        print(f"  auto-stop after {settings.auto_stop_silence_minutes:g} min of silence")
    print("Press Ctrl+C here or run `leus-notes stop` to finish.", flush=True)
    try:
        result = recorder.record(
            devices,
            meeting.me_audio,
            meeting.them_audio,
            silence_seconds=settings.auto_stop_silence_minutes * 60,
            silence_threshold_db=settings.silence_threshold_db,
        )
    except BaseException:
        control.clear_active(settings.run_dir)
        if not meeting.has_audio():
            shutil.rmtree(meeting.folder, ignore_errors=True)
        raise
    request = control.take_stop_request(settings.run_dir) if result.reason is StopReason.STOP_COMMAND else None
    control.clear_active(settings.run_dir)
    meeting.stopped_at = now()
    meeting.save()
    print(f"\nRecording stopped after {format_duration(result.seconds)}.")
    try:
        decision = decide_after_stop(result, request, people, settings)
    except KeyboardInterrupt:
        print(f"\nNot processed. The audio is kept in {meeting.folder}")
        print(f"Run `leus-notes process {meeting.folder.name}` when you want the notes.")
        return 130
    if decision is None:
        shutil.rmtree(meeting.folder)
        print("Recording discarded.")
        return 0
    meeting.people = str(decision)
    meeting.save()
    return run_pipeline(meeting, settings)


def describe_outputs(devices: recorder.Devices) -> str:
    default, *others = [monitor.removesuffix(".monitor") for monitor in devices.monitors]
    return f"{default} (+{len(others)} other output{'s' if len(others) != 1 else ''})" if others else default


def decide_after_stop(
    result: RecordingResult,
    request: control.StopRequest | None,
    people: PeopleCount,
    settings: Settings,
) -> PeopleCount | None:
    if result.reason is StopReason.SILENCE:
        print(f"No sound for {settings.auto_stop_silence_minutes:g} min, so the recording stopped automatically.")
        return people
    if result.reason is StopReason.STOP_COMMAND:
        if request and request.discard:
            return None
        return PeopleCount.parse(request.people) if request and request.people else people
    if not sys.stdin.isatty():
        return people
    if result.seconds < settings.min_duration_seconds and confirm(f"Recording is only {result.seconds:.0f} s. Discard?"):
        return None
    return ask_people(people)


def confirm(question: str) -> bool:
    return input(f"{question} [Y/n]: ").strip().lower() in ("", "y", "yes")


def ask_people(people: PeopleCount) -> PeopleCount:
    while True:
        answer = input(f"Number of people who spoke? [{people}]: ").strip()
        if not answer:
            return people
        try:
            return PeopleCount.parse(answer)
        except PeopleCountError as error:
            print(error)


def stop_command(args: argparse.Namespace, settings: Settings) -> int:
    active = control.read_active(settings.run_dir)
    if not active:
        raise UserError("no recording is running.")
    people = PeopleCount.parse(args.number_of_people) if args.number_of_people else None
    discard = False
    if people is None and sys.stdin.isatty():
        elapsed = (now() - datetime.fromisoformat(active.started_at)).total_seconds()
        if elapsed < settings.min_duration_seconds and confirm(f"Recording is only {elapsed:.0f} s. Discard?"):
            discard = True
        else:
            people = ask_people(PeopleCount.parse(active.people))
    if control.read_active(settings.run_dir) != active:
        raise UserError("the recording has already stopped.")
    control.write_stop_request(
        settings.run_dir, control.StopRequest(discard=discard, people=str(people) if people else None)
    )
    try:
        os.kill(active.pid, signal.SIGTERM)
    except ProcessLookupError as error:
        raise UserError("the recording process has already ended.") from error
    if discard:
        print("Recording discarded.")
    else:
        print("Recording stopped. The notes will be ready in a few minutes; watch for the desktop notification.")
    return 0


def status_command(args: argparse.Namespace, settings: Settings) -> int:
    active = control.read_active(settings.run_dir)
    if active:
        elapsed = (now() - datetime.fromisoformat(active.started_at)).total_seconds()
        print(f"Recording '{active.title}' for {format_timestamp(elapsed)} (people: {active.people})")
        print(f"  {active.folder}")
        return 0
    print("Not recording.")
    try:
        meeting = find_meeting(settings.meetings_dir)
    except MeetingNotFound:
        return 0
    if meeting.notes_path.exists():
        state = "notes ready"
    elif meeting.segments_path.exists():
        state = "transcribed, notes missing"
    else:
        state = "not processed yet"
    if meeting.has_audio():
        state += f", audio kept ({meeting.keep_audio_reason})" if meeting.keep_audio_reason else ", audio kept"
    print(f"Latest meeting: {meeting.folder.name} ({state})")
    if meeting.google_doc_url:
        print(f"  Google Doc: {meeting.google_doc_url}")
    return 0


def pick_meeting(settings: Settings, reference: str | None, *, transcribed: bool = False) -> Meeting:
    active = control.read_active(settings.run_dir)
    recording = Path(active.folder).resolve() if active else None
    meeting = find_meeting(settings.meetings_dir, reference, transcribed=transcribed, skip=recording)
    if recording and meeting.folder.resolve() == recording:
        raise UserError(f"'{meeting.folder.name}' is still being recorded.")
    return meeting


def process_command(args: argparse.Namespace, settings: Settings) -> int:
    meeting = pick_meeting(settings, args.meeting)
    if args.number_of_people:
        people = PeopleCount.parse(args.number_of_people)
        if meeting.segments_path.exists() and not args.redo_speakers:
            raise UserError("this meeting is already transcribed. Add --redo-speakers to use the new number of people.")
        meeting.people = str(people)
        meeting.save()
    return run_pipeline(meeting, settings, redo_speakers=args.redo_speakers, rewrite_notes=args.notes)


def names_command(args: argparse.Namespace, settings: Settings) -> int:
    reference, assignments = split_names_arguments(args.items)
    meeting = pick_meeting(settings, reference, transcribed=True)
    utterances = load_utterances(meeting.segments_path)
    speakers = speaker_ids(utterances)
    if not speakers:
        if any(utterance.speaker == THEM for utterance in utterances):
            raise UserError(
                "speakers weren't separated for this meeting, so there is nobody to name. "
                "Run `leus-notes process --redo-speakers` while the audio still exists."
            )
        raise UserError("nobody else spoke in this meeting.")
    print(f"Meeting: {meeting.folder.name}")
    names = dict(meeting.names)
    if assignments:
        for speaker, name in assignments:
            if speaker not in speakers:
                listed = ", ".join(f"Speaker {item}" for item in speakers)
                raise UserError(f"there is no Speaker {speaker} in this meeting ({listed}).")
            if name:
                names[speaker] = name
            else:
                names.pop(speaker, None)
    elif sys.stdin.isatty():
        for speaker in speakers:
            name = ask_name(speaker, utterances, names.get(speaker))
            if name:
                names[speaker] = name
    else:
        raise UserError('pass names like "Speaker 1=Marko", or run the command in a terminal.')
    if names == meeting.names:
        print("No changes.")
        return 0
    meeting.names = names
    meeting.save()
    return run_pipeline(meeting, settings, rewrite_notes=True, notify_when_done=False)


def split_names_arguments(items: list[str]) -> tuple[str | None, list[tuple[str, str]]]:
    reference = None
    assignments = []
    for item in items:
        if "=" not in item:
            if reference is not None:
                raise UserError(f"give one meeting only (got '{reference}' and '{item}').")
            reference = item
            continue
        match = ASSIGNMENT.match(item)
        if not match:
            raise UserError(f"'{item}' should look like \"Speaker 1=Marko\".")
        assignments.append((match[1], match[2].strip()))
    return reference, assignments


def ask_name(speaker: str, utterances: list[Utterance], current: str | None) -> str | None:
    spoken = [utterance for utterance in utterances if utterance.speaker == speaker]
    longest = sorted(spoken, key=lambda utterance: len(utterance.text), reverse=True)[:SAMPLE_LINES]
    print(f"\nSpeaker {speaker} — first heard {format_timestamp(min(utterance.start for utterance in spoken))}")
    for sample in sorted(longest, key=lambda utterance: utterance.start):
        text = sample.text if len(sample.text) <= SAMPLE_WIDTH else sample.text[: SAMPLE_WIDTH - 1] + "…"
        print(f'  [{format_timestamp(sample.start)}] "{text}"')
    answer = input(f"Name for Speaker {speaker}{f' [{current}]' if current else ''}: ").strip()
    return answer or current


def run_pipeline(
    meeting: Meeting,
    settings: Settings,
    *,
    redo_speakers: bool = False,
    rewrite_notes: bool = False,
    notify_when_done: bool = True,
) -> int:
    try:
        notes_written = process(
            meeting, settings, Engine(settings), redo_speakers=redo_speakers, rewrite_notes=rewrite_notes
        )
    except KeyboardInterrupt:
        print(f"\nProcessing interrupted. Run `leus-notes process {meeting.folder.name}` to finish.")
        return 130
    except Exception as error:
        message = str(error) if isinstance(error, (PipelineError, NotesError)) else f"{type(error).__name__}: {error}"
        print(f"leus-notes: {message}", file=sys.stderr)
        if meeting.has_audio():
            print(f"The audio is kept. Run `leus-notes process {meeting.folder.name}` to try again.")
        if notify_when_done:
            notify("Meeting notes failed", f"{meeting.title}: {message}")
        return 1
    print(f"\nNotes:      {meeting.notes_path}")
    print(f"Transcript: {meeting.transcript_path}")
    if meeting.keep_audio_reason and meeting.has_audio():
        print(f"The audio is kept because {meeting.keep_audio_reason}.")
    if notify_when_done:
        notify("Meeting notes ready", f"{meeting.title}\n{meeting.notes_path}")
    if notes_written and meeting.google_doc_id:
        return refresh_google_doc(meeting, settings)
    return 0


def refresh_google_doc(meeting: Meeting, settings: Settings) -> int:
    retry = f"Run `leus-notes share {meeting.folder.name}`"
    try:
        doc = sharing.refresh(meeting, sharing.connect(settings, interactive=False))
    except SharingError as error:
        print(f"leus-notes: the Google Doc was not updated: {error}", file=sys.stderr)
        print(f"{retry} to try again.", file=sys.stderr)
        return 1
    if doc is None:
        print(f"The Google Doc of this meeting was deleted or is in the trash. {retry} to create a new one.")
        return 0
    print(f"Google Doc: {doc.url} (updated)")
    return 0


def share_command(args: argparse.Namespace, settings: Settings) -> int:
    meeting = pick_meeting(settings, args.meeting, transcribed=True)
    if not meeting.notes_path.exists():
        raise UserError(f"'{meeting.folder.name}' has no notes yet. Run `leus-notes process {meeting.folder.name}` first.")
    shared = sharing.share(meeting, settings, sharing.connect(settings, interactive=True))
    if shared.new_folder:
        print(f"Created the Drive folder '{settings.share_folder}': {shared.new_folder.url}")
        print("Share that folder with your team once in Google Drive; every Doc in it is then visible to them.")
    print(f"{'Updated' if shared.updated else 'Created'} Google Doc for '{meeting.title}': {shared.doc.url}")
    return 0


def notify(title: str, body: str) -> None:
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "--app-name=leus-notes", title, body], check=False)


def doctor_command(args: argparse.Namespace, settings: Settings) -> int:
    return doctor.run(settings, download_models=args.download_models)

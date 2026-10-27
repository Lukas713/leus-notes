import json
import re
from datetime import datetime, timezone

import pytest
import requests

from leus_notes import cli, sharing
from leus_notes.cli import UserError, refresh_google_doc, share_command
from leus_notes.config import Settings
from leus_notes.doctor import google_check
from leus_notes.meeting import Meeting
from leus_notes.sharing import (
    DOCUMENT_TYPE,
    FILES_URL,
    FOLDER_TYPE,
    UPLOAD_URL,
    Drive,
    SharingError,
    notes_html,
    query_literal,
    refresh,
    share,
)

START = datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc)
NOTES = """# Sample call

- **Speakers:** Lukas, Marko

## Summary
Lukas agreed to send the offer.

## Action items
| Owner | Task | Due |
|---|---|---|
| Lukas / Marko | Send offer | Friday |
"""


class FakeResponse:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self.data = data

    def json(self):
        return self.data


class FakeGoogleDrive:
    def __init__(self):
        self.files = {}
        self.requests = []

    def add(self, **fields):
        file_id = f"id{len(self.files) + 1}"
        self.files[file_id] = {"trashed": False, **fields}
        return file_id

    def found(self, file_id):
        return FakeResponse(200, {"id": file_id, "webViewLink": f"https://drive.test/{file_id}"})

    def documents(self):
        return {key: value for key, value in self.files.items() if value["mimeType"] == DOCUMENT_TYPE}

    def folders(self):
        return {key: value for key, value in self.files.items() if value["mimeType"] == FOLDER_TYPE}

    def request(self, method, url, params=None, json=None, data=None, headers=None, timeout=None):
        self.requests.append((method, url))
        if method == "GET" and url == FILES_URL:
            name = re.search(r"name = '(.*)' and", params["q"])[1]
            matches = [key for key, value in self.folders().items() if value["name"] == name and not value["trashed"]]
            return FakeResponse(200, {"files": [self.found(key).data for key in matches]})
        if method == "GET":
            file_id = url.rsplit("/", 1)[1]
            if file_id not in self.files:
                return FakeResponse(404, {"error": {"message": "File not found"}})
            return FakeResponse(200, {"id": file_id, "trashed": self.files[file_id]["trashed"]})
        if method == "POST" and url == FILES_URL:
            return self.found(self.add(**json))
        metadata, html = parse_multipart(data, headers["Content-Type"])
        if method == "POST" and url == UPLOAD_URL:
            return self.found(self.add(**metadata, html=html))
        file_id = url.rsplit("/", 1)[1]
        self.files[file_id].update(metadata, html=html)
        return self.found(file_id)


def parse_multipart(body, content_type):
    boundary = content_type.split("boundary=")[1]
    _, metadata_part, html_part, _ = body.decode().split(f"--{boundary}")
    metadata = json.loads(metadata_part.split("\r\n\r\n", 1)[1])
    html = html_part.split("\r\n\r\n", 1)[1].removesuffix("\r\n")
    return metadata, html


def make_meeting(tmp_path, title="Sample call", notes=NOTES):
    meeting = Meeting.create(tmp_path / "meetings", title, START, "3", {})
    if notes:
        meeting.notes_path.write_text(notes)
    return meeting


def make_settings(tmp_path):
    return Settings(root=tmp_path / "root", meetings_dir=tmp_path / "meetings")


def test_notes_html_keeps_formatting():
    html = notes_html(NOTES)
    assert "<h1>Sample call</h1>" in html
    assert "<strong>Speakers:</strong> Lukas, Marko" in html
    assert "<p>Lukas agreed to send the offer.</p>" in html
    assert "<td>Lukas / Marko</td>" in html


def test_query_literal_escapes_quotes():
    assert query_literal("Lukas's notes") == "'Lukas\\'s notes'"


def test_first_share_creates_folder_and_doc(tmp_path):
    google = FakeGoogleDrive()
    meeting = make_meeting(tmp_path)
    shared = share(meeting, make_settings(tmp_path), Drive(google))
    [(folder_id, folder)] = google.folders().items()
    [(doc_id, doc)] = google.documents().items()
    assert folder["name"] == "Meeting notes"
    assert shared.new_folder.id == folder_id
    assert not shared.updated
    assert doc["name"] == "Sample call – 2026-10-24"
    assert doc["parents"] == [folder_id]
    assert "Lukas agreed" in doc["html"]
    reloaded = Meeting.load(meeting.folder)
    assert (reloaded.google_doc_id, reloaded.google_doc_url) == (doc_id, f"https://drive.test/{doc_id}")


def test_next_meeting_reuses_the_folder(tmp_path):
    google = FakeGoogleDrive()
    config = make_settings(tmp_path)
    share(make_meeting(tmp_path, "First"), config, Drive(google))
    shared = share(make_meeting(tmp_path, "Second"), config, Drive(google))
    assert shared.new_folder is None
    assert len(google.folders()) == 1
    assert len(google.documents()) == 2


def test_sharing_again_updates_the_same_doc(tmp_path):
    google = FakeGoogleDrive()
    config = make_settings(tmp_path)
    meeting = make_meeting(tmp_path)
    first = share(meeting, config, Drive(google))
    meeting.notes_path.write_text(NOTES.replace("Marko", "Ana"))
    second = share(meeting, config, Drive(google))
    assert second.updated
    assert second.doc == first.doc
    [doc] = google.documents().values()
    assert "Ana" in doc["html"]
    assert "Marko" not in doc["html"]


def test_sharing_a_trashed_doc_creates_a_new_one(tmp_path):
    google = FakeGoogleDrive()
    config = make_settings(tmp_path)
    meeting = make_meeting(tmp_path)
    first = share(meeting, config, Drive(google))
    google.files[first.doc.id]["trashed"] = True
    second = share(meeting, config, Drive(google))
    assert not second.updated
    assert second.doc.id != first.doc.id
    assert meeting.google_doc_id == second.doc.id


def test_refresh_updates_a_shared_doc(tmp_path):
    google = FakeGoogleDrive()
    config = make_settings(tmp_path)
    meeting = make_meeting(tmp_path)
    shared = share(meeting, config, Drive(google))
    meeting.notes_path.write_text(NOTES.replace("Marko", "Ana"))
    assert refresh(meeting, Drive(google)) == shared.doc
    assert "Ana" in google.files[shared.doc.id]["html"]


def test_refresh_never_recreates_a_removed_doc(tmp_path):
    google = FakeGoogleDrive()
    config = make_settings(tmp_path)
    meeting = make_meeting(tmp_path)
    shared = share(meeting, config, Drive(google))
    google.files[shared.doc.id]["trashed"] = True
    google.requests.clear()
    assert refresh(meeting, Drive(google)) is None
    assert [method for method, _ in google.requests] == ["GET"]
    del google.files[shared.doc.id]
    assert refresh(meeting, Drive(google)) is None
    assert len(google.documents()) == 0


def test_refresh_without_a_doc_does_nothing(tmp_path):
    google = FakeGoogleDrive()
    assert refresh(make_meeting(tmp_path), Drive(google)) is None
    assert google.requests == []


def test_refused_request_becomes_a_sharing_error():
    class Refusing:
        def request(self, method, url, **kwargs):
            return FakeResponse(403, {"error": {"message": "Insufficient permissions"}})

    with pytest.raises(SharingError, match=r"\(403\): Insufficient permissions"):
        Drive(Refusing()).folder("Meeting notes")


def test_network_failure_becomes_a_sharing_error():
    class Offline:
        def request(self, method, url, **kwargs):
            raise requests.ConnectionError("no route to host")

    with pytest.raises(SharingError, match="could not reach Google Drive"):
        Drive(Offline()).is_live("id1")


def test_share_command_needs_notes(tmp_path):
    meeting = make_meeting(tmp_path, notes=None)
    meeting.segments_path.write_text('{"utterances": []}')
    with pytest.raises(UserError, match="no notes yet"):
        share_command(cli.build_parser().parse_args(["share"]), make_settings(tmp_path))


def test_share_command_prints_the_link(tmp_path, monkeypatch, capsys):
    google = FakeGoogleDrive()
    monkeypatch.setattr(sharing, "connect", lambda settings, interactive: Drive(google))
    meeting = make_meeting(tmp_path)
    meeting.segments_path.write_text('{"utterances": []}')
    assert share_command(cli.build_parser().parse_args(["share"]), make_settings(tmp_path)) == 0
    output = capsys.readouterr().out
    assert "Created the Drive folder 'Meeting notes': https://drive.test/id1" in output
    assert "Created Google Doc for 'Sample call': https://drive.test/id2" in output


def test_refresh_failure_keeps_notes_and_explains_retry(tmp_path, monkeypatch, capsys):
    def expired(settings, interactive):
        raise SharingError("not logged in to Google")

    monkeypatch.setattr(sharing, "connect", expired)
    meeting = make_meeting(tmp_path)
    meeting.google_doc_id = "id9"
    assert refresh_google_doc(meeting, make_settings(tmp_path)) == 1
    assert f"leus-notes share {meeting.folder.name}" in capsys.readouterr().err
    assert meeting.notes_path.read_text() == NOTES


def test_google_check_states(tmp_path):
    config = make_settings(tmp_path)
    assert "not set up" in google_check(config).detail
    config.google_dir.mkdir(parents=True)
    (config.google_dir / sharing.CLIENT_FILE).write_text("{}")
    assert "not logged in" in google_check(config).detail
    (config.google_dir / sharing.TOKEN_FILE).write_text("{}")
    assert google_check(config).ok


def test_raw_html_in_notes_is_shown_as_text():
    html = notes_html("Marko said <img src=https://tracker.test/x> twice.")
    assert "<img" not in html
    assert "&lt;img src=https://tracker.test/x&gt;" in html


def test_damaged_token_means_logging_in_again(tmp_path):
    google_dir = tmp_path / "google"
    google_dir.mkdir()
    (google_dir / sharing.TOKEN_FILE).write_text('{"refresh_tok')
    with pytest.raises(SharingError, match="Run `leus-notes share` to log in"):
        sharing.load_credentials(google_dir, interactive=False)


def test_wrong_client_file_is_explained(tmp_path):
    google_dir = tmp_path / "google"
    google_dir.mkdir()
    (google_dir / sharing.CLIENT_FILE).write_text('{"something": "else"}')
    with pytest.raises(SharingError, match="not a Google OAuth client file"):
        sharing.load_credentials(google_dir, interactive=True)

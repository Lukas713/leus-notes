from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import Settings
from .meeting import Meeting

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
FILES_URL = "https://www.googleapis.com/drive/v3/files"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_TYPE = "application/vnd.google-apps.folder"
DOCUMENT_TYPE = "application/vnd.google-apps.document"
CLIENT_FILE = "client_secret.json"
TOKEN_FILE = "token.json"
REQUEST_TIMEOUT_SECONDS = 60
SETUP_HINT = "See 'Sharing notes as Google Docs' in README.md."


class SharingError(Exception):
    pass


class Response(Protocol):
    status_code: int

    def json(self) -> Any: ...


class Session(Protocol):
    def request(self, method: str, url: str, **kwargs: Any) -> Response: ...


@dataclass(frozen=True)
class DriveFile:
    id: str
    url: str


@dataclass(frozen=True)
class Shared:
    doc: DriveFile
    updated: bool
    new_folder: DriveFile | None = None


def notes_html(markdown: str) -> str:
    from markdown_it import MarkdownIt

    body = MarkdownIt("commonmark", {"html": False}).enable("table").render(markdown)
    return f'<html><head><meta charset="utf-8"></head><body>{body}</body></html>'


def doc_title(meeting: Meeting) -> str:
    return f"{meeting.title} – {meeting.started_at:%Y-%m-%d}"


def multipart_body(metadata: dict[str, Any], html: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n{html}\r\n"
        f"--{boundary}--\r\n"
    )
    return body.encode(), f"multipart/related; boundary={boundary}"


def query_literal(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


class Drive:
    def __init__(self, session: Session):
        self.session = session

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        from google.auth.exceptions import GoogleAuthError
        from requests import RequestException

        try:
            return self.session.request(method, url, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
        except GoogleAuthError as error:
            raise SharingError(f"the Google login no longer works ({error}). Run `leus-notes share` to log in again.") from error
        except RequestException as error:
            raise SharingError(f"could not reach Google Drive: {error}") from error

    def call(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        return checked(self.request(method, url, **kwargs)).json()

    def is_live(self, file_id: str) -> bool:
        response = self.request("GET", f"{FILES_URL}/{file_id}", params={"fields": "id,trashed"})
        if response.status_code == 404:
            return False
        return not checked(response).json().get("trashed", False)

    def folder(self, name: str) -> tuple[DriveFile, bool]:
        query = f"mimeType = '{FOLDER_TYPE}' and name = {query_literal(name)} and trashed = false"
        found = self.call(
            "GET", FILES_URL, params={"q": query, "fields": "files(id,webViewLink)", "orderBy": "createdTime"}
        )["files"]
        if found:
            return DriveFile(found[0]["id"], found[0]["webViewLink"]), False
        created = self.call(
            "POST", FILES_URL, params={"fields": "id,webViewLink"}, json={"name": name, "mimeType": FOLDER_TYPE}
        )
        return DriveFile(created["id"], created["webViewLink"]), True

    def create_document(self, title: str, html: str, folder_id: str) -> DriveFile:
        body, content_type = multipart_body({"name": title, "mimeType": DOCUMENT_TYPE, "parents": [folder_id]}, html)
        created = self.call(
            "POST",
            UPLOAD_URL,
            params={"uploadType": "multipart", "fields": "id,webViewLink"},
            data=body,
            headers={"Content-Type": content_type},
        )
        return DriveFile(created["id"], created["webViewLink"])

    def update_document(self, file_id: str, title: str, html: str) -> DriveFile:
        body, content_type = multipart_body({"name": title}, html)
        updated = self.call(
            "PATCH",
            f"{UPLOAD_URL}/{file_id}",
            params={"uploadType": "multipart", "fields": "id,webViewLink"},
            data=body,
            headers={"Content-Type": content_type},
        )
        return DriveFile(updated["id"], updated["webViewLink"])


def checked(response: Response) -> Response:
    if not 200 <= response.status_code < 300:
        raise SharingError(f"Google Drive refused the request ({response.status_code}): {error_message(response)}")
    return response


def error_message(response: Response) -> str:
    try:
        return str(response.json()["error"]["message"])
    except (ValueError, KeyError, TypeError):
        return "no details"


def connect(settings: Settings, *, interactive: bool) -> Drive:
    try:
        from google.auth.transport.requests import AuthorizedSession
    except ImportError as error:
        raise SharingError(f"the Google libraries are missing ({error.name}). Run: python3 install.py") from error

    return Drive(AuthorizedSession(load_credentials(settings.google_dir, interactive=interactive)))


def load_credentials(google_dir: Path, *, interactive: bool):
    from google.auth.exceptions import RefreshError, TransportError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_path = google_dir / TOKEN_FILE
    try:
        credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES) if token_path.exists() else None
    except (OSError, ValueError):
        credentials = None
    if credentials and credentials.valid:
        return credentials
    if credentials and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except TransportError as error:
            raise SharingError(f"could not reach Google: {error}") from error
        except RefreshError:
            credentials = None
        else:
            save_token(token_path, credentials.to_json())
            return credentials
    if not interactive:
        raise SharingError("not logged in to Google, or the login has expired. Run `leus-notes share` to log in.")
    credentials = log_in(google_dir)
    save_token(token_path, credentials.to_json())
    return credentials


def log_in(google_dir: Path):
    from google_auth_oauthlib.flow import InstalledAppFlow
    from oauthlib.oauth2.rfc6749.errors import OAuth2Error

    client_file = google_dir / CLIENT_FILE
    if not client_file.exists():
        google_dir.mkdir(mode=0o700, exist_ok=True)
        raise SharingError(f"Google sharing is not set up yet: {client_file} is missing. {SETUP_HINT}")
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES)
    except ValueError as error:
        raise SharingError(f"{client_file} is not a Google OAuth client file ({error}). {SETUP_HINT}") from error
    try:
        return flow.run_local_server(
            port=0,
            open_browser=True,
            authorization_prompt_message="Log in to Google in your browser. If no window opened, visit:\n{url}",
            success_message="leus-notes may now create Docs in your Google Drive. You can close this tab.",
        )
    except OAuth2Error as error:
        raise SharingError(f"the Google login did not complete: {error.description or error.error}") from error


def save_token(path: Path, token: str) -> None:
    path.parent.mkdir(mode=0o700, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(token)


def remember(meeting: Meeting, doc: DriveFile) -> None:
    meeting.google_doc_id = doc.id
    meeting.google_doc_url = doc.url
    meeting.save()


def refresh(meeting: Meeting, drive: Drive) -> DriveFile | None:
    if not meeting.google_doc_id or not drive.is_live(meeting.google_doc_id):
        return None
    doc = drive.update_document(meeting.google_doc_id, doc_title(meeting), notes_html(meeting.notes_path.read_text()))
    remember(meeting, doc)
    return doc


def share(meeting: Meeting, settings: Settings, drive: Drive) -> Shared:
    doc = refresh(meeting, drive)
    if doc:
        return Shared(doc, updated=True)
    folder, created = drive.folder(settings.share_folder)
    doc = drive.create_document(doc_title(meeting), notes_html(meeting.notes_path.read_text()), folder.id)
    remember(meeting, doc)
    return Shared(doc, updated=False, new_folder=folder if created else None)

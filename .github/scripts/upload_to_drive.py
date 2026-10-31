#!/usr/bin/env python3
"""Upload the nightly database dump to Google Drive."""

from pathlib import Path
import os
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload


# This script authenticates as the repository owner's own Google account using
# a pre-generated OAuth refresh token, not as a service account. See
# scripts/get_refresh_token.py for how that refresh token was originally generated.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
TOKEN_URI = "https://oauth2.googleapis.com/token"
FOLDER_NAME = "Liftbook backups"
FOLDER_MIME = "application/vnd.google-apps.folder"


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"{name} environment variable is missing or empty.")
    return value


def backup_folder(drive_service, preferred_id: str) -> str:
    """The folder to upload into.

    drive.file only reaches files this app made, so a folder made by hand (or
    in another Google account) is invisible to it. Use GDRIVE_FOLDER_ID when the
    app can see it; otherwise find or create the app's own "Liftbook backups".
    """
    if preferred_id:
        try:
            drive_service.files().get(fileId=preferred_id, fields="id").execute()
            return preferred_id
        except HttpError as error:
            if error.resp.status != 404:
                raise
            print("GDRIVE_FOLDER_ID isn't reachable with this sign-in; using the app's own folder.")
    found = (
        drive_service.files()
        .list(
            q=f"name = '{FOLDER_NAME}' and mimeType = '{FOLDER_MIME}' and trashed = false",
            fields="files(id)",
            spaces="drive",
        )
        .execute()
        .get("files", [])
    )
    if found:
        return found[0]["id"]
    folder = (
        drive_service.files()
        .create(body={"name": FOLDER_NAME, "mimeType": FOLDER_MIME}, fields="id")
        .execute()
    )
    print(f"Created the Google Drive folder '{FOLDER_NAME}'.")
    return folder["id"]


def main() -> None:
    dump_file = Path(require_env("DUMP_FILE"))
    preferred_folder_id = os.environ.get("GDRIVE_FOLDER_ID", "")
    client_id = require_env("GDRIVE_OAUTH_CLIENT_ID")
    client_secret = require_env("GDRIVE_OAUTH_CLIENT_SECRET")
    refresh_token = require_env("GDRIVE_OAUTH_REFRESH_TOKEN")

    if not dump_file.exists():
        sys.exit(f"Backup file was not found: {dump_file}")

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    credentials.refresh(Request())

    drive_service = build("drive", "v3", credentials=credentials)
    file_metadata = {
        "name": dump_file.name,
        "parents": [backup_folder(drive_service, preferred_folder_id)],
    }
    media = MediaFileUpload(
        str(dump_file),
        mimetype="application/octet-stream",
        resumable=True,
    )

    uploaded_file = (
        drive_service.files()
        .create(
            body=file_metadata,
            media_body=media,
            fields="id,name",
        )
        .execute()
    )

    print(
        "Uploaded "
        f"{uploaded_file['name']} to Google Drive "
        f"with file ID {uploaded_file['id']}."
    )


if __name__ == "__main__":
    main()

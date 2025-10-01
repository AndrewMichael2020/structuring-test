"""Minimal Google Drive helper with console OAuth flow and CSV upload.

This file is intentionally minimal: it provides a console-based auth flow that
works in Codespaces (prints a URL, asks for the code) and a function to
upload/replace a CSV file by name.

Configure via environment variables:
- DRIVE_OAUTH_CLIENT_SECRETS: path to client_secret_*.json (required)
- DRIVE_OAUTH_TOKEN_PATH: where to save the token (default .credentials/drive_token.json)
- DRIVE_FOLDER_ID: optional Drive folder id to create the file in
"""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional

# Load .env automatically in dev environments so users don't need to export
# environment variables manually.
try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
    else:
        # fallback to default behavior (look for environment variables already set)
        load_dotenv()
except Exception:
    # python-dotenv may not be installed in some runtime environments; that's OK
    pass

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import logging

SCOPES = [
    # Use the broader Drive scope so the app can update files the user didn't create with the app.
    # drive.file limits access to files created or opened by the app; that caused PERMISSION_DENIED
    # when updating an existing spreadsheet owned by the same user. Using full drive scope
    # requires re-consent but enables reliable upsert behavior.
    "https://www.googleapis.com/auth/drive",
    # Needed to update native Google Sheets in-place
    "https://www.googleapis.com/auth/spreadsheets",
]


def _ensure_creds(client_secrets_path: str, token_path: str, interactive: bool = False) -> Credentials:
    # Try to load existing token
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            # Refresh if possible and expired so token reuse works across runs
            if creds and not creds.valid:
                try:
                    if creds.expired and creds.refresh_token:
                        creds.refresh(Request())
                        # persist refreshed token
                        with open(token_path, "w", encoding="utf-8") as fh:
                            fh.write(creds.to_json())
                except Exception:
                    # if refresh fails, fall back to interactive flow below
                    # refresh failed; we'll fall through to interactive branch unless
                    # the environment doesn't allow interactive consent. To avoid
                    # blocking the main pipeline in non-interactive environments,
                    # we do not launch an interactive console flow here. Instead
                    # raise an informative error so callers can decide to skip
                    # Drive upload or run the one-time helper script.
                    raise RuntimeError("No valid Drive credentials available (refresh failed). Run scripts/drive_oauth.py to obtain credentials.")
            if creds and creds.valid:
                return creds
        except Exception:
            pass
    # If we reached this point there is no valid token on disk.
    # If interactive is requested (only from the helper), run the console flow.
    if interactive:
        flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, SCOPES)
        # Console flow prints an auth URL and asks for the code or redirected URL.
        creds = flow.run_console()
        # Save token
        p = Path(token_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as fh:
            fh.write(creds.to_json())
        return creds

    # Otherwise, avoid blocking the main pipeline waiting for console input.
    raise RuntimeError("No Drive credentials found. Run scripts/drive_oauth.py for one-time interactive consent or set DRIVE_SERVICE_ACCOUNT_JSON for non-interactive auth.")

    # (unreachable in non-interactive branch)


class DriveStorage:
    def __init__(self, creds: Credentials, folder_id: Optional[str] = None):
        self.creds = creds
        self.service = build("drive", "v3", credentials=creds)
        self.folder_id = folder_id

    @classmethod
    def from_env(cls) -> "DriveStorage":
        client = os.environ.get("DRIVE_OAUTH_CLIENT_SECRETS")
        if not client:
            likely = Path(__file__).parent / "env"
            candidates = [p for p in likely.iterdir()] if likely.exists() else []
            client = None
            for p in candidates:
                if p.name.startswith("client_secret") and p.suffix == ".json":
                    client = str(p)
                    break
        if not client or not Path(client).exists():
            raise EnvironmentError("No client secret JSON found. Set DRIVE_OAUTH_CLIENT_SECRETS or place client_secret*.json in ./env/")

        token_path = os.environ.get("DRIVE_OAUTH_TOKEN_PATH", ".credentials/drive_token.json")
        creds = _ensure_creds(client, token_path)
        folder = os.environ.get("DRIVE_FOLDER_ID")
        return cls(creds, folder_id=folder)

    def _rows_to_csv_bytes(self, rows: Iterable[Dict[str, object]], fieldnames: List[str]) -> bytes:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            row = {k: ("" if r.get(k) is None else str(r.get(k))) for k in fieldnames}
            writer.writerow(row)
        return output.getvalue().encode("utf-8")

    def _persisted_file_id_path(self) -> str:
        # allow overriding via env var, otherwise use a default path in .credentials
        return os.environ.get("DRIVE_ARTIFACTS_FILE_ID_PATH", ".credentials/drive_artifacts_file_id.txt")

    def _read_persisted_file_id(self) -> Optional[str]:
        # allow a direct env override of the file id as well
        # Allow opt-in usage of a persisted id. By default we do NOT use a persisted
        # id to avoid accidental updates/duplication across runs. Set
        # DRIVE_USE_PERSISTED_ID=1 to enable the persisted-id behavior.
        use_persist = str(os.environ.get("DRIVE_USE_PERSISTED_ID", "")).lower() in ("1", "true", "yes")
        if use_persist:
            env_id = os.environ.get("DRIVE_ARTIFACTS_FILE_ID")
            if env_id:
                return env_id
        p = Path(self._persisted_file_id_path())
        try:
            if p.exists():
                return p.read_text(encoding="utf-8").strip() or None
        except Exception:
            pass
        return None

    def _write_persisted_file_id(self, file_id: str) -> None:
        p = Path(self._persisted_file_id_path())
        try:
            # Only write the persisted id when explicitly enabled via env var.
            use_persist = str(os.environ.get("DRIVE_USE_PERSISTED_ID", "")).lower() in ("1", "true", "yes")
            if not use_persist:
                return
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(file_id), encoding="utf-8")
        except Exception:
            # best-effort only; don't fail the upload if writing the id fails
            pass

    def _update_sheet_from_csv(self, file_id: str, csv_bytes: bytes, drive_filename: str) -> Dict:
        """Update an existing native Google Sheet (preserve file id) using the Sheets API.

        This method WILL NOT delete or recreate the spreadsheet. It will clear the first sheet
        and write the CSV contents into it. Raises Exception on failure so callers can handle it.
        """
        logger = logging.getLogger(__name__)
        sheets_service = build("sheets", "v4", credentials=self.creds)
        # get first sheet title
        meta = sheets_service.spreadsheets().get(spreadsheetId=file_id, fields="sheets(properties(title)),spreadsheetUrl").execute()
        sheets_info = meta.get("sheets", [])
        sheet_title = "Sheet1"
        if sheets_info:
            sheet_title = sheets_info[0].get("properties", {}).get("title", "Sheet1")

        decoded = csv_bytes.decode("utf-8")
        rdr = csv.reader(io.StringIO(decoded))
        values = [r for r in rdr]

        range_name = f"'{sheet_title}'"
        # Clear and update
        sheets_service.spreadsheets().values().clear(spreadsheetId=file_id, range=range_name).execute()
        result = sheets_service.spreadsheets().values().update(
            spreadsheetId=file_id,
            range=range_name,
            valueInputOption="RAW",
            body={"values": values},
        ).execute()
        # return metadata similar to the other branches
        return {"id": file_id, "name": drive_filename, "webViewLink": meta.get("spreadsheetUrl")}

    def upload_or_replace(self, name: str, rows: Iterable[Dict[str, object]]) -> Dict:
        rows = list(rows)
        if not rows:
            raise ValueError("No rows to upload")
        fieldnames = sorted({k for r in rows for k in r.keys()})
        csv_bytes = self._rows_to_csv_bytes(rows, fieldnames)
        media = MediaIoBaseUpload(io.BytesIO(csv_bytes), mimetype="text/csv")

        # Find existing
        q = f"name='{name}' and trashed=false"
        if self.folder_id:
            q += f" and '{self.folder_id}' in parents"
        res = self.service.files().list(q=q, fields="files(id,name,webViewLink)", includeItemsFromAllDrives=True, supportsAllDrives=True).execute()
        files = res.get("files", [])
        # support reset behavior
        reset_mode = str(os.environ.get('DRIVE_RESET_ON_UPLOAD', '')).lower() in ('1', 'true', 'yes')
        if reset_mode and files:
            for f in files:
                try:
                    self.service.files().delete(fileId=f.get('id'), supportsAllDrives=True).execute()
                except Exception:
                    pass
            files = []
        if files:
            file_id = files[0]["id"]
            updated = self.service.files().update(fileId=file_id, media_body=media, fields="id,name,webViewLink", supportsAllDrives=True).execute()
            return updated

        metadata = {"name": name}
        if self.folder_id:
            metadata["parents"] = [self.folder_id]
        created = self.service.files().create(body=metadata, media_body=media, fields="id,name,webViewLink", supportsAllDrives=True).execute()
        return created

    def upload_or_replace_bytes(self, name: str, data: bytes, mimetype: str = "application/octet-stream") -> Dict:
        """Upload raw bytes to Drive, replacing an existing file with the same name (and folder) if present."""
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mimetype)

        q = f"name='{name}' and trashed=false"
        if self.folder_id:
            q += f" and '{self.folder_id}' in parents"
        res = self.service.files().list(q=q, fields="files(id,name,webViewLink)", includeItemsFromAllDrives=True, supportsAllDrives=True).execute()
        files = res.get("files", [])
        # support reset behavior
        reset_mode = str(os.environ.get('DRIVE_RESET_ON_UPLOAD', '')).lower() in ('1', 'true', 'yes')
        if reset_mode and files:
            for f in files:
                try:
                    self.service.files().delete(fileId=f.get('id'), supportsAllDrives=True).execute()
                except Exception:
                    pass
            files = []
        if files:
            file_id = files[0]["id"]
            updated = self.service.files().update(fileId=file_id, media_body=media, fields="id,name,webViewLink", supportsAllDrives=True).execute()
            return updated

        metadata = {"name": name}
        if self.folder_id:
            metadata["parents"] = [self.folder_id]
        created = self.service.files().create(body=metadata, media_body=media, fields="id,name,webViewLink", supportsAllDrives=True).execute()
        return created

    def save_artifacts_csv(
        self,
        rows: Iterable[Dict[str, object]],
        drive_filename: str = "artifacts.csv",
        fieldnames: Optional[Iterable[str]] = None,
    ) -> Dict:
        """Serialize rows to CSV and upload/replace on Drive.

        If `fieldnames` is provided, that exact column order will be used. Otherwise
        fieldnames are inferred from the union of keys in `rows` (sorted).
        """
        rows = list(rows)
        if not rows:
            raise ValueError("No rows to write")
        if fieldnames is None:
            inferred = sorted({k for r in rows for k in r.keys()})
            fieldnames = inferred
        else:
            # ensure we have a list (and preserve order)
            fieldnames = list(fieldnames)

        csv_bytes = self._rows_to_csv_bytes(rows, list(fieldnames))
        media = MediaIoBaseUpload(io.BytesIO(csv_bytes), mimetype="text/csv")

        q = f"name='{drive_filename}' and trashed=false"
        if self.folder_id:
            q += f" and '{self.folder_id}' in parents"
        # Support an optional reset mode where existing files are deleted before
        # creating new ones. This is controlled by the environment variable
        # DRIVE_RESET_ON_UPLOAD (truthy values: '1', 'true', 'yes'). When set,
        # we remove any existing files matching the name and clear the persisted id
        # to force creation of a fresh sheet.
        reset_mode = str(os.environ.get('DRIVE_RESET_ON_UPLOAD', '')).lower() in ('1', 'true', 'yes')

        # If reset requested and a persisted file exists, attempt to delete it.
        if reset_mode:
            persisted_id = self._read_persisted_file_id()
            if persisted_id:
                try:
                    self.service.files().delete(fileId=persisted_id, supportsAllDrives=True).execute()
                except Exception:
                    # ignore delete errors; continue to attempt name-based deletions
                    pass
                # clear persisted id file so we don't reuse a deleted id
                try:
                    self._write_persisted_file_id('')
                except Exception:
                    pass

        # If user has persisted a file id, prefer updating that file directly (avoids duplicate creations)
        persisted_id = self._read_persisted_file_id()
        if persisted_id:
            try:
                # retrieve metadata to check mime type
                file = self.service.files().get(fileId=persisted_id, fields="id,name,mimeType,webViewLink,parents", supportsAllDrives=True).execute()
                mime = file.get("mimeType")
                # If native sheet, update in-place; otherwise attempt an update of the bytes
                if mime == "application/vnd.google-apps.spreadsheet":
                    updated = self._update_sheet_from_csv(persisted_id, csv_bytes, drive_filename)
                    return updated
                else:
                    media_update = MediaIoBaseUpload(io.BytesIO(csv_bytes), mimetype="text/csv")
                    updated = self.service.files().update(fileId=persisted_id, media_body=media_update, fields="id,name,webViewLink", supportsAllDrives=True).execute()
                    return updated
            except Exception:
                # If persisted id is invalid or update fails, fall back to name-based lookup/creation
                pass

        # include mimeType so we can decide whether to convert to native Sheet
        res = self.service.files().list(q=q, fields="files(id,name,mimeType,webViewLink,parents)", includeItemsFromAllDrives=True, supportsAllDrives=True).execute()
        files = res.get("files", [])
        # If reset mode requested: delete any name-matching files found
        if reset_mode and files:
            for f in files:
                try:
                    self.service.files().delete(fileId=f.get('id'), supportsAllDrives=True).execute()
                except Exception:
                    pass
            # clear files list to force creation below
            files = []
        if files:
            file = files[0]
            file_id = file.get("id")
            mime = file.get("mimeType")
            # If existing file is already a Google Sheet, try to update it in-place
            if mime == "application/vnd.google-apps.spreadsheet":
                # For a DB-like spreadsheet we must update in-place to preserve the file ID.
                try:
                    updated = self._update_sheet_from_csv(file_id, csv_bytes, drive_filename)
                    # persist the id so future runs update the same file
                    try:
                        self._write_persisted_file_id(file_id)
                    except Exception:
                        pass
                    return updated
                except Exception:
                    # If the in-place update fails, we raise so the caller can decide; do not delete/recreate silently.
                    raise

        # Create a native Google Sheet using the Sheets API, then populate it and (optionally) move into folder
        try:
            sheets_service = build("sheets", "v4", credentials=self.creds)
            sheet_body = {"properties": {"title": drive_filename}}
            ss = sheets_service.spreadsheets().create(body=sheet_body, fields="spreadsheetId,spreadsheetUrl").execute()
            spreadsheet_id = ss.get("spreadsheetId")
            # Move the spreadsheet into the target folder if provided
            if self.folder_id and spreadsheet_id:
                try:
                    # fetch current parents
                    file_meta = self.service.files().get(fileId=spreadsheet_id, fields="parents", supportsAllDrives=True).execute()
                    prev_parents = ",".join(file_meta.get("parents", []) or [])
                    self.service.files().update(
                        fileId=spreadsheet_id,
                        addParents=self.folder_id,
                        removeParents=prev_parents,
                        fields="id,parents",
                        supportsAllDrives=True,
                    ).execute()
                except Exception:
                    # best-effort; continue even if moving fails
                    pass

            # Populate the new spreadsheet with our CSV contents
            if spreadsheet_id:
                updated_meta = self._update_sheet_from_csv(spreadsheet_id, csv_bytes, drive_filename)
                # Persist the created file id so future runs can update the same file (opt-in)
                try:
                    self._write_persisted_file_id(spreadsheet_id)
                except Exception:
                    pass
                return updated_meta
        except Exception:
            # If Sheets API creation fails, fall back to Drive create with CSV upload (may create a binary CSV file)
            pass

        # Fallback: upload as a plain CSV file (not converted)
        metadata = {"name": drive_filename}
        if self.folder_id:
            metadata["parents"] = [self.folder_id]
        created = self.service.files().create(body=metadata, media_body=media, fields="id,name,webViewLink,parents,mimeType", supportsAllDrives=True).execute()
        return created

    def save_artifacts_json(self, docs: Iterable[Dict], drive_filename: str = "artifacts.json") -> Dict:
        """Serialize a collection of JSON docs and upload/replace as a single JSON file on Drive."""
        docs = list(docs)
        if not docs:
            raise ValueError("No docs to write")
        payload = json.dumps(docs, ensure_ascii=False, indent=2).encode("utf-8")
        return self.upload_or_replace_bytes(drive_filename, payload, mimetype="application/json; charset=utf-8")


def quick_smoke_upload():
    ds = DriveStorage.from_env()
    res = ds.upload_or_replace(os.environ.get("DRIVE_ARTIFACTS_FILENAME", "artifacts.csv"), [{"test":"ok","value":1}])
    print("Upload result:", res)

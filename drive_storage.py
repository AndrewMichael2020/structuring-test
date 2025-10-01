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

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _ensure_creds(client_secrets_path: str, token_path: str) -> Credentials:
    # Try to load existing token
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            if creds and creds.valid:
                return creds
        except Exception:
            pass

    # Run console flow
    flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, SCOPES)
    try:
        creds = flow.run_console()
    except Exception:
        # Some environments don't implement run_console(); build a manual
        # authorization URL that includes a redirect_uri so Google returns a
        # code in the URL. The client secret for this project lists
        # "http://localhost" as an allowed redirect, so set that explicitly.
        redirect_uri = os.environ.get("DRIVE_OAUTH_REDIRECT", "http://localhost")
        try:
            flow.redirect_uri = redirect_uri
        except Exception:
            # ignore if not supported
            pass

        auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline", include_granted_scopes="true")
        print("Open this URL in your browser and complete consent. If the browser cannot reach the local loopback server, the address bar will still contain the redirect URL with the authorization code (it will look like http://localhost/?code=... ).\n")
        print(auth_url)
        print("\nAfter consent, copy the full redirect URL from your browser's address bar and paste it here, or paste just the value of the 'code' parameter.")
        raw = input("Paste redirect URL or code: ").strip()
        # Accept either the full redirect URL or just the code
        code = raw
        if raw.lower().startswith("http"):
            # parse code param
            from urllib.parse import parse_qs, urlparse

            parsed = urlparse(raw)
            qs = parse_qs(parsed.query)
            code_list = qs.get("code") or qs.get("authcode")
            if not code_list:
                raise ValueError("No 'code' parameter found in the URL you pasted.")
            code = code_list[0]

        flow.fetch_token(code=code)
        creds = flow.credentials

    # Save token
    p = Path(token_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    return creds


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
        # include mimeType so we can decide whether to convert to native Sheet
        res = self.service.files().list(q=q, fields="files(id,name,mimeType,webViewLink,parents)", includeItemsFromAllDrives=True, supportsAllDrives=True).execute()
        files = res.get("files", [])
        if files:
            file = files[0]
            file_id = file.get("id")
            mime = file.get("mimeType")
            # If existing file is already a Google Sheet, update it in-place
            if mime == "application/vnd.google-apps.spreadsheet":
                updated = self.service.files().update(fileId=file_id, media_body=media, fields="id,name,webViewLink", supportsAllDrives=True).execute()
                return updated
            else:
                # Delete the old CSV (to avoid duplicates) then create a new native Google Sheet
                try:
                    self.service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
                except Exception:
                    # ignore deletion errors and fall back to creating a new file
                    pass

        # Create a native Google Sheet by uploading the CSV bytes and setting mimeType to spreadsheet
        metadata = {"name": drive_filename, "mimeType": "application/vnd.google-apps.spreadsheet"}
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

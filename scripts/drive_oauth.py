#!/usr/bin/env python3
"""Console helper: run the OAuth console flow and save token."""

import os
from pathlib import Path
import sys

workspace_root = Path(__file__).resolve().parents[1]
if str(workspace_root) not in sys.path:
    sys.path.insert(0, str(workspace_root))

# Try to load .env automatically so users who edited .env don't need to export
# variables manually.
try:
    from dotenv import load_dotenv

    env_path = workspace_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()
except Exception:
    pass

from drive_storage import _ensure_creds


def main():
    client = os.environ.get("DRIVE_OAUTH_CLIENT_SECRETS")
    if not client:
        likely = Path(__file__).resolve().parents[1] / "env"
        if likely.exists():
            for p in likely.iterdir():
                if p.name.startswith("client_secret") and p.suffix == ".json":
                    client = str(p)
                    break
    if not client:
        print("No client secret found. Set DRIVE_OAUTH_CLIENT_SECRETS or put client_secret*.json in ./env/")
        return
    token_path = os.environ.get("DRIVE_OAUTH_TOKEN_PATH", ".credentials/drive_token.json")
    print("Using client secrets:", client)
    print("Saving token to:", token_path)
    creds = _ensure_creds(client, token_path, interactive=True)
    print("Done. You can now run scripts that use DriveStorage.from_env().")


if __name__ == "__main__":
    main()

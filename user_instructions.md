# User Instructions — Backend pipeline

This file summarizes the recommended commands and flows to run the backend extraction → service pipeline → upload steps for the project.

Prerequisites
- Python environment (3.8+). Install Python deps:

```bash
pip install -r requirements.txt
```

- If you want to upload programmatically via the Python client, install the Google Cloud Storage client:

```bash
pip install google-cloud-storage
```

- Ensure GCP credentials are available for uploads. Either run:

```bash
gcloud auth login
gcloud auth application-default login
```

or set a service account key in your environment:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
```

- Set the target bucket name (example):

```bash
export GCS_BUCKET=accident-reports-artifacts
```

Interactive flow (recommended when exploring)
1. Start the interactive CLI:

```bash
python main.py
```

2. Follow the menu to:
- Process a single URL, or
- Run a batched extraction from a URLs file, and then
- Optionally run the service pipeline (assign IDs, merge/fuse, generate reports).

The interactive menu is useful because it lets you inspect generated files before continuing to the next step.

Non-interactive (batch) recommended sequence
1. Extract artifacts in batch (this writes artifacts and exits):

```bash
python main.py --urls-file urls.txt --batch-size 7 --mode text-only
```

Note: when using `--urls-file`, the script will perform the batched extraction and exit (it does not automatically continue into the service pipeline in that same process).

2. Run the service pipeline (assign IDs, merge, generate reports):

```bash
python main.py --assign-event-ids --merge-events --generate-reports
```

- Use `--dry-run` to preview what would be written:

```bash
python main.py --assign-event-ids --merge-events --generate-reports --dry-run
```

Uploads: reports and manifest
There are two upload flows in the repo; choose one depending on your environment.

A) Automatic/upload-from-service (best-effort)
- `services/report_service.py` will attempt a best-effort upload of the canonical manifest (`reports/list.json`) after it writes report markdown files when `GCS_BUCKET` is set. This is non-fatal and will not break the pipeline if upload fails.

B) Manual/explicit (recommended for control)
- Upload `.md` report files using the provided script which supports both the Python client and `gsutil`:

Preview (dry-run):

```bash
python3 scripts/upload_reports.py --dry-run --method auto
```

Upload (auto-select method):

```bash
python3 scripts/upload_reports.py --method auto
```

Force client library (requires `google-cloud-storage`):

```bash
python3 scripts/upload_reports.py --method client
```

Force gsutil:

```bash
python3 scripts/upload_reports.py --method gsutil
```

- Build + upload the canonical manifest (list.json):

```bash
python3 scripts/build_reports_list.py            # writes /tmp/list.json
GCS_BUCKET=$GCS_BUCKET python3 scripts/build_reports_list.py --upload
# or manually:
# gsutil cp /tmp/list.json gs://$GCS_BUCKET/reports/list.json
```

Notes
- `build_reports_list.py` currently uses `gsutil` for uploading the manifest; if you prefer the upload be performed by the Python client or centralized in `upload_reports.py`, I can change `build_reports_list.py` to call the uploader instead.
- If you plan to run uploads in CI, ensure either the google-cloud-storage package is installed and credentials are present, or that gsutil (Cloud SDK) is available on the runner.
- To verify a manifest is present after upload:

```bash
curl -sS https://storage.googleapis.com/$GCS_BUCKET/reports/list.json | jq .
```

Quick example (end-to-end)

```bash
# prerequisites
pip install -r requirements.txt
pip install google-cloud-storage   # optional but recommended
export GCS_BUCKET=accident-reports-artifacts
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json

# 1) Run batch extraction
python main.py --urls-file urls.txt --batch-size 7 --mode text-only

# 2) Run service pipeline to produce reports
python main.py --assign-event-ids --merge-events --generate-reports

# 3) Upload reports and manifest manually (if not already uploaded automatically)
python3 scripts/upload_reports.py --method auto
python3 scripts/build_reports_list.py --upload
```

If you want me to centralize uploads (call uploader from `build_reports_list.py` or convert the manifest upload to the Python client), say which approach you prefer and I'll implement it.

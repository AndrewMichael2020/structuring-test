# Structuring Test — news article extractor and accident metadata pipeline

This project aims to collect and structure information about underreported, under-analyzed mountain accidents in British Columbia, Alberta, and Washington State. There is no centralized ledger for these incidents; details are scattered across local news, SAR posts, park/advisory bulletins, and social media—and they often disappear behind CDNs, redesigns, or paywalls. This repository builds a decentralized, auditable pipeline that pulls key facts into a lightweight ledger you can query, verify, and evolve over time.

## Why this matters (value in practice)

- Turn fleeting stories into durable facts: Headlines vanish; `artifacts/**/accident_info.json` and a canonical CSV give you a persistent, searchable record.
- Compare across publishers: Structured fields (dates, location hints, people counts, outcomes, agencies) enable cross-source analysis—no more manual copy/paste.
- Preserve context and traceability: Every run writes an auditable folder with inputs/outputs, so you can reproduce and review decisions.
- Cost and speed discipline: Text-first extraction, small focused prompts, batch LLM calls where possible, and strict call caps.
- Low ops: No database required. By default, the ledger is rebuilt deterministically from on-disk JSON into `artifacts/artifacts.csv`.
- Model-agnostic: Models are configured in `config.json`; GPT-5-style “no temperature” models are supported seamlessly.

## What you get

- Per-URL artifact folders: `artifacts/<domain>/<timestamp>/` with the extracted article text, structured `accident_info.json`, and optionally OCR-enriched image metadata.
- A canonical CSV: `artifacts/artifacts.csv` rebuilt from all on-disk JSON with stable headers and auto-added count columns.
- A batching mode: Feed a list of URLs and get per-URL JSON artifacts in one pass, with minimal artifacts even when some pages are teaser-only.

## Quickstart

- Python 3.10+ recommended. Install dependencies from `requirements.txt`.
- Optional: set `OPENAI_API_KEY` to enable LLM extraction; otherwise minimal artifacts are still produced.
- Run a single URL in full mode:
  - `python main.py "https://example.com/article" --mode all`
- Run batched LLM extraction from a file (one-per-line or comma-separated; `#` comments allowed):
  - `python main.py --urls-file urls.txt --mode text-only --batch-size 3`
- Rebuild the CSV deterministically from artifacts on disk:
  - `python -c "from store_artifacts import force_rebuild_and_upload_artifacts_csv; force_rebuild_and_upload_artifacts_csv()"`

You’ll see a summary like: `[rebuild] scanned 5 artifacts; wrote 5 rows -> artifacts/artifacts.csv`.

## What’s inside (architecture)

- `fetcher.py` — HTML fetching and article-text extraction. Strategy:
  1) static fetch and best-effort parsing
  2) AMP fallback (`rel=amphtml`, `/amp`, `?outputType=amp`) when content is short/blocked
  3) Playwright fallback (stealth + short growth wait)
  4) readability-lxml fallback if content still looks like a teaser
- `accident_info.py` — Orchestrates text extraction and structured metadata:
  - Single URL: cleans text → pre-extracts hints → LLM → postprocess → write JSON.
  - Batch mode: groups URLs; one LLM call returns an array of JSON; falls back to minimal artifacts if needed.
  - In “all” mode the pipeline runs text analysis first, then image/OCR enrichment.
- `accident_llm.py` — LLM wrapper (OpenAI). Respects model config and call caps; omits temperature for GPT-5-family models.
- `accident_preextract.py` — Deterministic regex heuristics (dates, people, fall height, etc.).
- `accident_postprocess.py` — Normalization/validation and heuristic confidence scoring.
- `store_artifacts.py` — Rebuilds `artifacts/artifacts.csv` from on-disk JSON; adds counts and a raw `artifact_json` column; optional Drive upload.
- `main.py` — CLI. Modes: `all`, `text-only`, `ocr-only`. Batch input via `--urls-file`.

## Flow overview

1) Fetch & extract article text (robust parsing + AMP + Playwright + Readability fallbacks).
2) Clean and focus the text (title, paragraphs, boilerplate trimming). Preserve a `scraped_full_text` for traceability.
3) Deterministic pre-extraction (regex/gazetteer hints) to seed the LLM.
4) LLM extraction (text-only or batch): structured JSON per story.
5) Postprocess + confidence: consolidate types, normalize dates, compute confidence.
6) Optional OCR: image candidates and light condition analysis.
7) Rebuild CSV from JSON (no DB required) and optionally upload to Drive.

## Configuration

- `config.json` (and optional `config.local.json`) control models and features:
  - `models.accident_info`: model for structured extraction (e.g., `gpt-5`).
  - `models.ocr_vision`: model for vision/OCR enrichment.
  - `timezone`, `gazetteer_enabled`.
- Environment variables:
  - `OPENAI_API_KEY` — enables LLM extraction.
  - `MAX_OPENAI_CALLS` — caps calls via `openai_call_manager`.
  - `PLAYWRIGHT_HEADLESS` — `true/false` for debugging; default `true`.
  - `PLAYWRIGHT_STEALTH` — `true/false` stealth mode.
  - `PLAYWRIGHT_NAV_TIMEOUT_MS` — navigation timeout (capped sensibly in code).
  - Drive: set environment as per `drive_storage.py` to enable upload.

## Batching

- Provide a file with URLs (one-per-line or comma-separated), with `#` comments allowed. See `urls.txt` template.
- Run `python main.py --urls-file urls.txt --mode text-only --batch-size 3`.
- Behavior under constraints:
  - If the LLM client is available, the batch call parses all items.
  - If it fails or returns fewer results, the pipeline writes minimal per-URL artifacts for the remainder (no silent drops).
- After runs, the CSV is rebuilt from disk; a concise summary is printed.

## Outputs

- `artifacts/<domain>/<timestamp>/accident_info.json` contains:
  - `source_url`, `extracted_at`, `article_text`, `scraped_full_text`
  - structured fields (people counts, dates, agencies, etc.)
  - an `extraction_confidence_score` (heuristic + optional model signal)
- `artifacts/artifacts.csv`:
  - Canonical fields in a stable order plus:
    - `artifact_json` (raw JSON per row)
    - count columns like `people_count`, `rescue_teams_count`, `*_urls_count`

## Operating principles

- Respect paywalls: no login or circumvention. AMP/Readability fallbacks are generic and use public HTML only.
- Deterministic rebuilds: CSV is always derived from on-disk JSON; no DB required.
- Cautious extraction: prompts emphasize precision and avoiding hallucination; we prefer explicit evidence in text.

## Troubleshooting

- “Wrote 0 artifacts” in batch mode:
  - Ensure `OPENAI_API_KEY` is set. With the latest batch delegation, GPT-5 will be used when the key is present; otherwise minimal artifacts are still written.
- Short/teaser outputs:
  - Some sites serve limited content without a session. AMP/Readability/Playwright fallbacks help; if still short, the LLM will extract what is present without making up facts.
- Playwright errors:
  - Install browsers if needed and try `PLAYWRIGHT_HEADLESS=false` locally to debug rendering.
- Call caps reached:
  - `MAX_OPENAI_CALLS` controls limits; minimal artifacts are written when caps are reached.

## Testing and quality

- The suite exercises batch fallbacks (client missing, cap reached, parse mismatch), LLM wrapper repair path, postprocessing/normalization, CSV rebuild (recursive scan and counts), orchestrator basics, and pre-extract/utilities.
- Run tests with `pytest`.

## Roadmap ideas

- Optional domain adapters for frequently used sources (kept out by default to remain generic).
- Cross-source de-duplication and event clustering.
- Enriched location normalization (gazetteer improvements) and map overlays.
- Light UI for browsing the ledger and exporting subsets.

---

This pipeline aims to help practitioners, reporters, and researchers turn ephemeral news into durable, structured knowledge—safely, transparently, and with minimal operational load.
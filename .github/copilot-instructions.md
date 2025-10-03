## Copilot Instructions (Project-Specific)

Purpose: Help an AI agent contribute productively to this repo (mountain accident ingestion + event/report pipeline + browsing frontend) without rediscovering architecture or conventions. Keep changes small, deterministic, and test-backed.

### High-Level Flow
1. Fetch & parse article HTML (fallback ladder: direct → AMP → Playwright → Readability) in `fetcher.py`.
2. Clean/focus text; deterministic regex + gazetteer hints (`accident_preextract.py`).
3. LLM extraction to strict JSON (`accident_info.py` + `accident_llm.py`, schema text in `accident_schema.py`). Single URL: one call; batch: one array response per group.
4. Postprocess & normalize (`accident_postprocess.py`) adding confidence + field cleaning.
5. (Optional) Image caption + OCR/Vision enrichment (`extract_captions.py`, `image_ocr.py`).
6. Service pipeline (optional, CLI flags / separate scripts):
   - Event clustering & ID assignment (`event_id_service.py`) → writes `event_id` into each `accident_info.json` (LLM w/ fallback deterministic keying + cache).
   - Event merge & fusion (`event_merge_service.py`) → `events/enriched/` + `events/fused/` (merge OCR + cross-source fuse with caching + deterministic fallback).
   - Report generation (`services/report_service.py`) → Markdown in `events/reports/` using planner → writer → verifier LLM chain.
7. CSV rebuild (`store_artifacts.py`) always derives canonical `artifacts/artifacts.csv` from on-disk JSON.

### Architectural Principles
* Deterministic first: heuristics, regex, caches, then minimal LLM calls (batch where possible) respecting caps (`openai_call_manager.py`).
* Idempotent outputs: Re-running does not duplicate logical records; CSV rebuild scans filesystem.
* Strict JSON discipline: Prompts insist on JSON-only; repair attempts exist—prefer extending existing repair logic over adding ad-hoc parsing.
* Caching: Clustering/merge/fusion caches keyed by content signatures / hash of inputs; clear with `--cache-clear`.
* Confidence: Deterministic scoring supplements or re-weights model score (see `compute_confidence` usage in `accident_info.py`).

### Key Conventions
* Directory layout:
  - `artifacts/<domain>/<timestamp>/accident_info.json` (per source run)
  - `events/{enriched,fused,reports}` derived post-ID assignment
  - Caches: `event_cluster_cache.json`, `event_merge_cache.json`, `event_fusion_cache.json`
* Never write DB by default; optional env toggles (`WRITE_TO_DB`, `WRITE_TO_DRIVE`). CSV rebuild is canonical.
* Model selection & service tier via `config.py` (merge precedence: env → `config.local.json` → `config.json` → defaults).
* GPT-5 family: temperature omitted automatically (`_supports_temperature`).
* Batch extraction: single LLM call returns array; mis-sized responses trimmed conservatively to `min(len(resp), len(batch))` with minimal fallbacks for remainder.
* Minimal artifact fallback: when LLM unavailable/capped/fails we still write artifact with pre-extracted hints + raw text.

### Environment Variables (Frequent)
OPENAI_API_KEY, MAX_OPENAI_CALLS, OPENAI_CALLS_PATH
Security note: Never commit a `.env` file with secrets. Use `.env.example` for local templates and put production/CI keys into repository or organization secrets (e.g., GitHub Secrets). If a key is accidentally committed, rotate it immediately.
SERVICE_TIER (standard|flex|batch|priority) — influences logging / planning only
TIMEZONE, GAZETTEER_ENABLED
PLAYWRIGHT_HEADLESS, PLAYWRIGHT_STEALTH, PLAYWRIGHT_NAV_TIMEOUT_MS (capped at 25s)
WRITE_TO_DRIVE, WRITE_TO_DB
Frontend: GCS_BUCKET, DEV_FAKE, LOCAL_REPORTS_DIR, PORT

### CLI & Typical Commands
* Single URL full pipeline: `python main.py <url> --mode all`
* Batch (text-only extraction path): `python main.py --urls-file urls.txt --mode text-only --batch-size 3`
* Assign event IDs: `python main.py --assign-event-ids`
* Merge + fuse: `python main.py --merge-events`
* Generate reports: `python main.py --generate-reports [--event-id <id>]`
* Force CSV rebuild (headless): `python -c "from store_artifacts import force_rebuild_and_upload_artifacts_csv; force_rebuild_and_upload_artifacts_csv()"`

### Testing Patterns
* Run all backend tests: `pytest` (tests mock network & LLM via monkeypatch; maintain test seams like `_client`, `can_make_call`).
* Frontend/server: in `app/`: `npm test` (Jest) + `npm run dev` for manual.
* When adding new extraction fields: update schema (`accident_schema.py`), extend postprocess mapping (`accident_postprocess._postprocess`), add test asserting presence or normalization.

### Safe Change Guidelines
* Preserve JSON schema compatibility—additive changes only unless accompanied by CSV rebuild logic & test updates.
* If adding new LLM calls: respect cap (check `can_make_call()` early) and log token usage via `token_tracker` if relevant.
* For new services: follow pattern—deterministic baseline + optional LLM enhancement + caching keyed by stable hash of inputs.
* Do not hardcode model names; import from `config.py`.
* Any new filesystem outputs: keep within existing top-level dirs (`artifacts/`, `events/`, `app/`) and document in this file if persistent.

### Common Pitfalls to Avoid
* Writing artifacts without `extracted_at` / `source_url` (downstream relies on both).
* Returning non-JSON tokens in LLM prompts—reuse strict system messages.
* Forgetting minimal fallback paths → tests assume resilience when LLM/cap absent.
* Introducing long blocking operations before cap check.

### Frontend Notes
* Display-only; markdown reports sanitized server-side (`sanitize-html`).
* Local dev uses `DEV_FAKE=1` or `LOCAL_REPORTS_DIR` for offline browsing.
* Reports path shape: `/reports/<event_id>.md` → served as HTML.

### When Unsure
Search for existing pattern first (e.g., how clustering handles parse repair) before adding a new utility. Keep diffs small, add/extend tests, and update this file if you introduce a new persistent artifact or env var.

---
End of project-specific Copilot instructions.

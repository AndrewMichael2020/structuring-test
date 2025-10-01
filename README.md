# Structuring Test — news article extractor and accident metadata pipeline

This project aims to **collect and structure information about underreported, under-analyzed mountain accidents** in **British Columbia, Alberta, and Washington State**. There is **no centralized ledger** for these incidents; details are scattered across local news, SAR posts, park/advisory bulletins, and social media—and they often disappear behind CDNs, redesigns, or paywalls. This repository builds a **decentralized, auditable pipeline** that pulls key facts into a lightweight ledger you can query, verify, and evolve over time.

**Why this exists**
- **Fragmented sources:** Incident details are inconsistent (names, dates, places) and easy to lose.
- **Underreporting:** Many events never reach official statistics or formal databases.
- **Actionable structure:** Standardized JSON fields (rescuers, area/park, trailhead, missing/recovered, ISO dates) enable analysis across publishers.
- **Context from images:** Optional vision pass extracts conditions (e.g., cornice, crown line, debris, wind loading, helicopter/longline, RECCO) that text alone may miss.
- **Traceability:** Each run writes `artifacts/<domain>/<timestamp>/` with inputs/outputs for reproducibility and auditing.
- **Cost/latency discipline:** Prefers small models and fast heuristics; uses a browser fallback only when needed; enforces timeouts to avoid hangs.

This repository contains a small pipeline that scrapes news/story web pages, extracts article text and image candidates (with filtering), runs OCR/vision and optional LLM-based extraction, and writes traceable artifacts. It was built to robustly extract structured accident metadata from diverse publisher pages while avoiding long hangs, unnecessary downloads, and runaway LLM usage.

Table of contents
- What problem this repo solves
- Key features and design goals
- Architecture and components
- Installation & dependencies
- Configuration & environment
- Usage (CLI and programmatic)
- Output artifacts and format
- Implementation details and heuristics
- Tuning and troubleshooting
- Testing and quality gates
- Security and privacy
- Contributing
- License

What problem this repo solves
--------------------------------
News sites vary wildly in HTML structure, use JS protection/captcha/CDN blocks, and often include a lot of irrelevant assets (logos, thumbnails, related headlines). This project solves a focused problem: given a URL to a news/story page (often about mountain/transport accidents), reliably extract the article text and relevant image candidates, then optionally run OCR/vision and an LLM to produce structured accident metadata (areas, rescuers, recovered/missing state, dates).

Key features and design goals
--------------------------------
- Robust HTML extraction: static-first parsing with a Playwright fallback for JS-protected pages.
- Bounded Playwright waits: navigation timeout capped at 25s so the pipeline never waits forever.
- Early image filtering: skip logos, affiliate images, and tiny assets before downloading to avoid mass downloads.
- OCR + LLM optional: support local OCR fallback (pytesseract/Pillow) and optional OpenAI calls for vision/structured extraction.
- LLM safety: lazy OpenAI init and a persistent per-run call counter to cap costs and avoid runaway API usage.
- Traceability: artifacts contain both a focused `article_text` used for LLMs and a `scraped_full_text` cleaned trace of the full scraped paragraphs.
- CLI run-modes: run all / text-only / ocr-only so you can control which stages are executed.

Architecture and components
------------------------------
Major modules
- `extract_captions.py` — collects image candidates and captions, performs HEAD checks and filtering, optionally downloads images and writes `captions.json`.
- `image_ocr.py` — local OCR helpers and optional LLM vision enrichment; respects OpenAI call cap.
- `accident_info.py` — extracts article text (static-first + Playwright fallback), cleans and trims it, and asks an LLM for structured accident metadata; writes `accident_info.json` including `article_text` and `scraped_full_text`.
- `openai_call_manager.py` — small utility to persist and cap OpenAI call counts across runs.
- `main.py` — orchestration/CLI to run extraction and enrichment in configurable modes.

Data flow
1. Start with a URL.
2. `extract_captions` fetches the HTML (requests + BeautifulSoup) and collects image/caption candidates; if static fetch looks blocked it falls back to Playwright.
3. Candidate images are filtered early by filename tokens and HEAD checks; only relevant images are downloaded.
4. `image_ocr` optionally performs local OCR and (if enabled and allowed by call caps) LLM enrichment.
5. `accident_info` extracts article text (prefers article container, captures title, preserves author/publish lines), builds `scraped_full_text` and a focused `article_text`, then optionally calls OpenAI for structured fields.
6. Artifacts are written under `artifacts/<domain>/<timestamp>/` as `captions.json`, `accident_info.json`, and downloaded images.

Installation & dependencies
---------------------------
This project runs under Python 3.10+ (tested in a dev container). Key dependencies are listed in `requirements.txt`.

Primary libraries used
- requests
- beautifulsoup4
- playwright (for JS-rendered fallbacks)
- pillow, pytesseract (local OCR)
- python-dateutil (optional -- date parsing)
- openai (optional, for LLM calls)

Install steps (example)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# If using Playwright render fallback, install browsers:
playwright install
```

Configuration & environment
----------------------------
This project looks for an OpenAI API key in the `OPENAI_API_KEY` environment variable.

To safely store your key locally, copy the template and create a `.env` file (this repo contains `.env.example` and `.env` is ignored by git):

```bash
cp .env.example .env
# edit .env and set OPENAI_API_KEY=sk-...
```

Important environment variables (all optional, with defaults in code):
- `OPENAI_API_KEY` — OpenAI API key (leave unset to skip LLM steps).
- `PLAYWRIGHT_NAV_TIMEOUT_MS` — milliseconds for Playwright nav/wait. Code enforces a max of 25000 (25s).
- `PLAYWRIGHT_STEALTH` — true/false, whether to add a tiny stealth/init script to the Playwright context.
- `IRRELEVANT_TOKENS` — comma-separated tokens used to filter image filenames/URLs early (logo, affiliate, thumbnail, etc.).
- `MAX_OPENAI_CALLS` — optional cap for how many OpenAI calls this run/session may perform.

Usage
------
CLI usage (quick):

```bash
# run full pipeline (captures images, OCR, and LLM extraction)
python main.py "https://example.com/news/article" --mode=all

# text-only mode (skip downloading images/ocr)
python main.py "https://example.com/news/article" --mode=text-only

# ocr-only (download images + OCR but skip LLM structured extraction)
python main.py "https://example.com/news/article" --mode=ocr-only
```

Programmatic usage
```python
from accident_info import extract_accident_info
json_path = extract_accident_info(url, base_output='artifacts')
```

Output artifacts
------------------
Artifacts are written to `artifacts/<domain>/<timestamp>/` with the following files:
- `captions.json` — list of image candidates (URL, filename, caption, heuristics)
- `accident_info.json` — structured output including:
	- `source_url` — original URL
	- `extracted_at` — ISO timestamp
	- `article_text` — focused trimmed text used for LLM extraction
	- `scraped_full_text` — cleaned full text (title + paragraphs) for traceability
	- any structured fields the LLM returned (e.g., `area`, `closest_municipality`, `rescuers`, `missing`, `recovered`, `missing_since`, `recovery_date`)
- downloaded image files (if download enabled)

Implementation details and heuristics
-------------------------------------
Article extraction
- Static-first: we fetch HTML with `requests` and try to find an `article`, `div.entry-content`, `main`, or the DOM node containing the most paragraph text.
- Playwright fallback: if the static fetch looks blocked (403, very short body, or explicit 'Access Denied'), we fall back to Playwright and render the page headlessly. Playwright waits are capped to 25s maximum to avoid indefinite waits.
- Title and author preservation: we try to capture an `h1`/`h2` title and preserve author/published lines detected by heuristics (e.g., lines that start with `By` followed by a capitalized name or contain `published`/`last updated`).
- `scraped_full_text` vs `article_text`: `scraped_full_text` is the fuller cleaned text (useful for traceability and auditing). `article_text` is a focused subset used for LLM extraction to reduce cost and noise.

Image extraction and filtering
- Early filtering tokens: images whose URL or filename contains tokens like `logo`, `thumbnail`, `affiliate`, `tracking`, etc., are filtered out before download.
- HEAD checks: before downloading images we perform a HEAD or light request to confirm content-type is an image and size exceeds a configurable minimum.
- Size checks: tiny images (< MIN_IMG_BYTES or small dimensions) are skipped to avoid OCR on icons.

LLM usage and safety
- Lazy OpenAI init: the OpenAI client is not constructed at import time; if `OPENAI_API_KEY` is missing, LLM steps are gracefully skipped.
- Call capping: `openai_call_manager.py` persists and enforces a per-run or per-repo cap so accidental mass requests don't happen.

Cleaning & trimming heuristics
- STOP_TOKENS and STOP_PREFIXES are used to filter obvious newsletter/signup/related-article lines.
- Trailing related headline runs are detected by looking for 3+ short paragraphs at the end of the full text and trimming them. This threshold can be tuned for aggressiveness.

Tuning and troubleshooting
---------------------------
Common adjustments you might want to make:
- Adjust `PLAYWRIGHT_NAV_TIMEOUT_MS` (max 25000 enforced) for slow pages.
- Tweak `IRRELEVANT_TOKENS` to add domain-specific logo/asset tokens to reduce irrelevant downloads.
- Make headline trimming more aggressive by reducing the tail-run threshold from 3 to 2 if you see short repeated headlines appended by the publisher.
- If Playwright stealth causes issues for a domain, disable `PLAYWRIGHT_STEALTH`.

Testing and quality gates
-------------------------
Quick checks to run locally:

```bash
# run the main extractor on a sample URL
python main.py "https://vancouversun.com/news/woman-dead-climbing-accident-squamish" --mode=all

# inspect artifact jsons in artifacts/<domain>/<timestamp>/
```

When editing extraction heuristics, prefer small iterative runs and inspect `scraped_full_text` to avoid over-aggressive token filtering.

Security and privacy
---------------------
- Never commit secrets. `.env` is ignored by git; use `.env.example` as a template.
- OpenAI calls can leak text to the LLM provider — review site privacy policies and redaction needs before sending sensitive content.

Contributing
-------------
Open a PR with focused changes. For scraping heuristics, include before/after sample artifacts so reviewers can verify improvements.

License
--------
MIT

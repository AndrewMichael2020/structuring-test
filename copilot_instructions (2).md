# 🧠 GitHub Copilot Instructions — Accident Data Extraction & Enrichment (GPT-5-mini)

## 🎯 Goal
Efficiently scrape, extract, and structure **mountain accident reports** into rich JSON objects using **minimal LLM calls**. Target: `gpt-4o-mini` scale cost (~$0.002–0.005/article).

---

## 🪜 **Overall Strategy**

### 1️⃣ **Pre-Extraction (Deterministic)**
Before calling any LLM:
- Parse article HTML (BeautifulSoup) and clean boilerplate.
- Extract **obvious structured values** using regex and lightweight NLP:
  - Dates (ISO and natural)
  - Names + ages (`[A-Z][a-z]+ [A-Z][a-z]+, \d{2}`)
  - Numbers of fatalities/injuries (`killed X`, `X injured`, etc.)
  - Coordinates, URLs, phone numbers
  - Headlines, bylines, publishing dates
- Store in a `pre_extracted` dict.  
👉 **No model calls here.**

---

### 2️⃣ **Main Extraction (Single JSON LLM Call per Article)**
- Pass:
  - ✅ Cleaned article text  
  - ✅ Pre-extracted fields  
  - ✅ Concise schema descriptions  
- Ask GPT-5-mini (`gpt-4o-mini` for prod) to fill as many fields as possible in **one JSON object**.
- Use `response_format={"type": "json_object"}` to enforce valid JSON.

👉 This replaces multiple per-field calls with one **multi-field structured call**.

---

### 3️⃣ **Optional Post-Processing (Batched Cleanup)**
- Identify invalid or ambiguous fields with regex/validators:
  - Dates that fail ISO parsing
  - Coordinates out of range
  - Malformed arrays or strings
- **Batch** 20–50 cleanup items and send to the LLM in one compact prompt, not per field.

👉 Examples: normalizing “Saturday afternoon” → `2025-05-11T15:00-07:00`, inferring region from lat/lon.

---

### 4️⃣ **Parallelization / Batching**
- For small articles, **group 3–5 per call** using clear delimiters and request a JSON array.
- Keep total prompt < 10 k tokens.

👉 This dramatically reduces overhead when scraping hundreds of articles.

---

## 📝 **Schema Used for Extraction**

```json
{
  "source_url": "string",
  "source_name": "string",
  "article_title": "string",
  "article_date_published": "YYYY-MM-DD",
  "region": "string",
  "mountain_name": "string",
  "route_name": "string",
  "activity_type": "string",
  "accident_type": "string",
  "accident_date": "YYYY-MM-DD",
  "accident_time_approx": "string",
  "num_people_involved": "int",
  "num_fatalities": "int",
  "num_injured": "int",
  "num_rescued": "int",
  "people": [
    {
      "name": "string",
      "age": "int",
      "sex": "string",
      "role": "string",
      "experience_level": "string",
      "outcome": "string",
      "injuries": "string",
      "rescue_status": "string",
      "hometown": "string",
      "occupation": "string",
      "nationality": "string",
      "quote_from_person": "string"
    }
  ],
  "rescue_teams_involved": ["string"],
  "response_agencies": ["string"],
  "rescue_method": "string",
  "response_difficulties": "string",
  "bodies_recovery_method": "string",
  "accident_summary_text": "string",
  "timeline_text": "string",
  "quoted_dialogue": ["string"],
  "notable_equipment_details": "string",
  "local_expert_commentary": "string",
  "family_statements": "string",
  "photo_urls": ["string"],
  "video_urls": ["string"],
  "related_articles_urls": ["string"],
  "fundraising_links": ["string"],
  "official_reports_links": ["string"],
  "fall_height_meters_estimate": "float",
  "self_rescue_boolean": "bool",
  "anchor_failure_boolean": "bool",
  "extraction_confidence_score": "0–1"
}
```

👉 Fields omitted if unavailable; **no `null`**.

---

## ⚡ **Prompt Template**

```text
System:
You are a precise information extractor. Return valid JSON only. Never invent data.

User:
SCHEMA: {short schema description}

PRE-EXTRACTED:
{json dict with regex-extracted values}

ARTICLE:
<cleaned article text here>
```

---

## 🧰 **Implementation Notes**
- Integrate into `accident_info.py` by:
  - Replacing the small `_PROMPT` with the new schema + pre-extracted injection.
  - Consolidating all field extractions into **one `_llm_extract()` call**.
- Use `_postprocess()` to:
  - Type-check values
  - Normalize dates with `_iso_or_none`
  - Drop malformed entries

---

## 💰 **Cost Profile**

| Step               | Calls | Cost        |
|---------------------|-------|------------|
| Pre-extract         | 0     | $0         |
| Main JSON call      | 1/article or 1/batch | Main cost |
| Post-process cleanup| 1/batch | Minimal |
| Parallelization     | amortized | Lower |

---

## 🚀 **Copilot Tasks**
- [ ] Replace old `_PROMPT` with schema prompt  
- [ ] Implement `pre_extract_fields(text) -> dict` before `_llm_extract`  
- [ ] Modify `_llm_extract` to include pre-extracted info and schema  
- [ ] Add batch cleanup function for ambiguous fields  
- [ ] Add parallel/batch processing option to CLI

---

## ✅ Example Output

```json
{
  "source_url": "https://vancouversun.com/news/example",
  "article_title": "Three Climbers Killed in Fall",
  "mountain_name": "Early Winters Spires",
  "accident_type": "fall",
  "activity_type": "climbing",
  "accident_date": "2025-05-11",
  "num_people_involved": 4,
  "num_fatalities": 3,
  "num_rescued": 1,
  "people": [
    {"name": "Anton Tselykh", "age": 38, "outcome": "survived", "injuries": "head trauma, internal injuries", "rescue_status": "self-evacuated"}
  ],
  "rescue_teams_involved": ["Okanogan County SAR"],
  "response_agencies": ["Sheriff’s Office"],
  "rescue_method": "self-evacuation and later medical transport",
  "timeline_text": "Four climbers fell Saturday afternoon; survivor trekked out overnight; SAR recovered bodies Sunday.",
  "fall_height_meters_estimate": 122.0,
  "anchor_failure_boolean": true,
  "extraction_confidence_score": 0.94
}
```

---

## 📝 References
Based on current `accident_info.py` scraping and LLM extraction structure.

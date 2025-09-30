# 🧗 GitHub Copilot Instructions — Climbing Difficulty Ratings Extraction (GPT-5-mini)

## 🎯 Goal
Enrich each accident JSON with **climbing difficulty ratings** for North American systems — particularly **YDS**, **NCCS**, **WI/AI**, **Mixed (M)**, and **Aid (A/C)** — for better filtering, normalization, and severity analysis.

---

## 🪜 **1️⃣ Fields to Add**

```json
"difficulty_metadata": {
  "primary_rating_system": "string",
  "difficulty_rating": "string",
  "difficulty_rating_normalized": "string",
  "rating_context": "string",
  "rating_interpretation": "string",
  "mixed_route_boolean": "boolean",

  "yds_rating": "string",
  "nccs_commitment_grade": "string",
  "ice_grade": "string",
  "mixed_grade": "string",
  "aid_grade": "string",
  "canadian_winter_commitment_grade": "string",

  "rating_difficulty_level": "easy | moderate | intermediate | advanced | expert | elite",
  "technicality_score": "float 0–1",
  "commitment_score": "float 0–1",
  "ice_technicality_score": "float 0–1",
  "mixed_technicality_score": "float 0–1",
  "aid_technicality_score": "float 0–1",

  "route_name_reported": "string",
  "route_length_description": "string",
  "approach_difficulty": "string",
  "notable_rating_features": "string"
}
```

---

## 🧰 **2️⃣ Extraction Logic**

### Pre-LLM Regex Pass
- Detect standard tokens to **reduce LLM work**:
  - YDS: `5\.[0-9]{1,2}[abcd]?` (e.g. `5.8`, `5.10b`)
  - NCCS: `Grade [IVX]+` (e.g. `Grade IV`)
  - Ice: `WI[0-9]+`, `AI[0-9]+`
  - Mixed: `M[0-9]+`
  - Aid: `A[0-9]+(\+)?` or `C[0-9]+(\+)?`
  - Canadian Winter: `Grade [IVX]+` + context like “Canadian” or WI prefix

Populate:
```python
pre_extracted["ratings_raw"] = ["5.10a", "Grade IV", "WI4"]
```

---

### Single JSON LLM Call
- Pass **cleaned article text** + `pre_extracted` ratings + short schema.  
- Ask Copilot to extract:
  - Structured ratings in `difficulty_metadata` block  
  - **Normalize** multiple ratings if present (`"5.10a, Grade IV, WI4"` → `difficulty_rating_normalized`)  
  - Provide brief interpretation text (`rating_interpretation`)  
  - Assign `rating_difficulty_level` (binned) and scores (0–1) heuristically.  
  - Mark `mixed_route_boolean` true if both rock and ice/mixed grades appear.

---

### Optional Post-Processing
- Validate that YDS, WI, M, A ratings conform to regex.  
- Derive `technicality_score` and `commitment_score` using mapping tables or heuristics:
  - YDS 5.0–5.5 ≈ 0.2–0.4, 5.10 ≈ 0.7, 5.13 ≈ 0.95
  - WI1–WI8 mapped to increasing ice_technicality_score
  - NCCS I–VII mapped to increasing commitment_score

---

## ⚡ **3️⃣ Example Output**

```json
"difficulty_metadata": {
  "primary_rating_system": "YDS",
  "difficulty_rating": "5.10a, Grade IV, WI4, M5, A2",
  "difficulty_rating_normalized": "YDS 5.10a; NCCS IV; WI4; M5; A2",
  "rating_context": "hardest pitch and overall route",
  "rating_interpretation": "Intermediate technical rock with sustained ice and moderate aid climbing; full-day commitment",
  "mixed_route_boolean": true,

  "yds_rating": "5.10a",
  "nccs_commitment_grade": "IV",
  "ice_grade": "WI4",
  "mixed_grade": "M5",
  "aid_grade": "A2",
  "canadian_winter_commitment_grade": "Grade IV",

  "rating_difficulty_level": "advanced",
  "technicality_score": 0.78,
  "commitment_score": 0.65,
  "ice_technicality_score": 0.72,
  "mixed_technicality_score": 0.60,
  "aid_technicality_score": 0.55,

  "route_name_reported": "Early Winters Spire South Arete",
  "route_length_description": "Three pitches, Grade IV",
  "approach_difficulty": "Remote alpine basin approach",
  "notable_rating_features": "Anchor failure at WI4 step"
}
```

---

## 🚀 **4️⃣ Copilot Tasks**

- [ ] Add `difficulty_metadata` block to schema.  
- [ ] Implement regex pre-extraction of rating tokens.  
- [ ] Modify `_llm_extract()` to include schema + `ratings_raw`.  
- [ ] Add score mapping helper functions.  
- [ ] Batch cleanup ambiguous ratings if needed.  
- [ ] Ensure one JSON LLM call handles **core fields + ratings together**.

---

## 📝 Notes
- This metadata enables **filtering and clustering** (e.g. “all WI4+ accidents with NCCS Grade ≥ V”) and **severity modeling**.  
- Ignore French Alpine, Alaska, and Scottish Winter systems.  
- Ratings should always be extracted **verbatim + normalized**.

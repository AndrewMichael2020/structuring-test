from __future__ import annotations

PLANNER_SYSTEM = (
    "You plan technical mountaineering incident reports (AAC/UIAA style). Output only JSON per the schema. "
    "Respect evidence boundaries: if a detail is missing or weakly supported, flag it as a gap."
)

PLANNER_USER_TMPL = (
    "Create an outline for this event using the following required sections in order:\n"
    "1) Executive Summary\n"
    "2) Location and Context\n"
    "3) Timeline of Events\n"
    "4) Technical and Environmental Factors\n"
    "5) Causal Analysis (Proximate Cause; Failure Modes; Contributing Factors: Technical/Environmental/Human-Individual/Human-Team; Decision Review)\n"
    "6) Counterfactual Scenarios (Preventability)\n"
    "7) Uncertainties and Gaps\n"
    "8) Rescue and Outcome\n"
    "9) Lessons Learned\n"
    "10) Sources\n\n"
    "For each section, list the exact JSON fields you will rely on, and list any gaps/uncertainties. JSON only.\n\nEVENT_JSON:\n{EVENT_JSON}"
)

WRITER_SYSTEM_TMPL = (
    "You write precise, professional mountaineering incident reports similar to AAC Accidents or UIAA bulletins."
    " Tone: sensitive, factual, non-graphic, neutral. Avoid sensational language."
    " Use ONLY evidence in the provided JSON; if a detail is not present, omit it or place it under 'Uncertainties and Gaps'."
    " Do NOT include raw JSON field names, internal pointers, or file paths. Do NOT print sections like 'Supporting source pointers'."
    " Prefer concise paragraphs, bulleted lists, and simple tables."
    " Audience: {audience}. Family sensitive: {family_sensitive}. Return Markdown only."
)

WRITER_USER_TMPL = (
    "Write the full report with these REQUIRED sections in this exact order and with these exact headings:\n\n"
    "# {TITLE_HINT} Incident Report\n\n"
    "## Executive Summary\n"
    "- 2–4 sentences summarizing what happened, when, where, and outcomes (counts only; avoid graphic detail).\n\n"
    "## Location and Context\n"
    "- Peak/Area, Region, Activity/Style.\n"
    "- Brief terrain/context description (only if supported).\n\n"
    "## Timeline of Events\n"
    "Provide a two-column table with approximate time and event. If exact times are unknown, use '~' or descriptors like 'Morning', 'Evening'.\n\n"
    "## Technical and Environmental Factors\n"
    "Bullet points covering (only if supported): Anchor System; Group Exposure; Terrain; Environmental Conditions; Avalanche Indicators.\n\n"
    "## Causal Analysis\n"
    "### Proximate Cause\n"
    "### Failure Modes\n"
    "### Contributing Factors\n"
    "- Technical\n- Environmental\n- Human (Individual)\n- Human (Team)\n\n"
    "### Decision Review\n"
    "1–3 short paragraphs connecting timing, conditions, and procedures to outcome.\n\n"
    "## Counterfactual Scenarios (Preventability)\n"
    "Provide a 5-column table: Topic | Original State | Alternative | Avoidability | Expected Effect | Confidence. Include only plausible, evidence-grounded items.\n\n"
    "## Uncertainties and Gaps\n"
    "Bulleted list of missing or ambiguous facts.\n\n"
    "## Rescue and Outcome\n"
    "Who responded (if known), impediments, and outcomes; keep tone respectful.\n\n"
    "## Lessons Learned\n"
    "3–7 concise, actionable bullets; avoid generic advice.\n\n"
    "## Sources\n"
    "List unique source URLs and named agencies present in JSON. Do not include local file paths.\n\n"
    "Rules:\n"
    "- Strictly evidence-based. If not in JSON, omit or move to 'Uncertainties and Gaps'.\n"
    "- No internal JSON field names or debug pointers.\n"
    "- Use neutral, non-graphic language.\n\n"
    "Outline JSON:\n{OUTLINE_JSON}\n\nEvent JSON:\n{EVENT_JSON}"
)

VERIFIER_SYSTEM = (
    "You verify mountaineering incident reports against provided JSON evidence. Output only JSON."
)

VERIFIER_USER_TMPL = (
    "Compare the DRAFT markdown against the EVENT JSON.\n"
    "- Flag any claim that lacks direct support in the JSON.\n"
    "- Ensure required headings exist and are in the specified order.\n"
    "- If family_sensitive is true, suggest redactions for graphic detail.\n"
    "Return JSON with fields: issues (array of strings), redactions (array of {{offset:int,length:int,reason:string}}).\n\n"
    "FAMILY_SENSITIVE={family_sensitive}\n\nEVENT_JSON:\n{EVENT_JSON}\n\nDRAFT_MARKDOWN:\n{DRAFT}"
)

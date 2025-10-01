"""Schema and prompt text for accident information extraction.

These constants are imported by the LLM extraction module and the
orchestrator. Kept separate to reduce churn when editing prompts.
"""

# -------------------- LLM schema and prompt --------------------

_SCHEMA_TEXT = """
Return an object containing any of the following keys (omit keys not present/
confident):
    source_url, source_name, article_title, article_date_published (YYYY-MM-DD),
    region, mountain_name, route_name, activity_type, accident_type,
    accident_date (YYYY-MM-DD), accident_time_approx, num_people_involved (int),
    num_fatalities (int), num_injured (int), num_rescued (int), people (array of
    objects with name, age, outcome, injuries, rescue_status, hometown),
    rescue_teams_involved (array), response_agencies (array), rescue_method,
    response_difficulties, bodies_recovery_method, accident_summary_text,
    timeline_text, quoted_dialogue (array), notable_equipment_details,
    local_expert_commentary, family_statements, photo_urls (array),
    video_urls (array), related_articles_urls (array), fundraising_links (array),
    official_reports_links (array), fall_height_meters_estimate (float),
    self_rescue_boolean (bool), anchor_failure_boolean (bool),
    extraction_confidence_score (0-1 float),
    accident_causes (object; detailed below)

accident_causes schema (omit any sub-keys you cannot support with evidence):
{
    "proximate_causes": [
        "anchor_failure", "rope_system_failure", "fall_on_steep_snow",
        "rockfall", "icefall", "avalanche", "crevasse_fall", "weather_change",
        "visibility_loss", "cornice_collapse", "terrain_trap_involvement",
        "slip_or_trip", "miscommunication", "medical_emergency",
        "equipment_malfunction"
    ],
    "contributing_factors": [
        "single_point_anchor", "anchor_old_or_weathered", "no_anchor_backup",
        "overloaded_anchor", "party_all_on_one_rope", "no_fixed_protection",
        "improper_knots", "inadequate_edge_protection", "unroped_on_glacier",
        "late_in_day", "rapid_temperature_change", "storm_arrival",
        "wind_slab_loading", "poor_visibility", "human_factor_heuristic_trap",
        "route_finding_error", "fatigue", "equipment_left_in_place",
        "improvised_anchor", "technical_skill_mismatch"
    ],
    "anchor_system": {
        "anchor_type": "piton|bolt|gear_anchor|snow_picket|bollard|v-thread|tree|
        rock_horn|natural|unknown",
        "num_points": int,
        "redundancy_present": bool,
        "anchor_condition": "new|good|old|weathered|rusted|unknown",
        "failure_mode": "pulled|snapped|sheared|unknown"
    },
    "rope_system": {
        "num_people_on_rope": int,
        "roped_for_descent": bool,
        "roped_for_ascent": bool,
        "rope_type": "single|half|twin|static|unknown",
        "belay_method": "rappel|lower|simul|pitch|running_belay|short_rope|
        unroped",
        "protection_in_place": bool,
        "failure_description": string,
        "knots_used": ["figure8", "munter", "clove", "unknown"]
    },
    "decision_factors": {
        "objective_hazard_awareness": "low|medium|high|unknown",
        "time_pressure": bool,
        "group_dynamics": "leader_follower|peer_pressure|independent|unknown",
        "experience_level_est": "beginner|intermediate|advanced|expert|mixed|
        unknown",
        "weather_forecast_considered": bool,
        "alternate_plan_available": bool
    },
    "equipment_status": {
        "critical_gear_present": [string],
        "gear_condition_issues": [string],
        "missing_expected_gear": [string],
        "equipment_failure_noted": [string]
    },
    "environmental_conditions": {
        "weather_change_timing": "before|during|after|none|unknown",
        "precipitation_intensity": "none|light|moderate|heavy",
        "temperature_trend": "warming|cooling|stable|unknown",
        "wind_speed_est": "calm|moderate|strong|storm",
        "snowpack_instability_signs": ["wind_slab", "rapid_warming",
        "storm_snow"],
        "visibility_class": "good|moderate|poor|whiteout"
    },
    "human_factors": {
        "group_size": int,
        "group_experience_mix": "homogeneous|mixed|unknown",
        "communication_method": ["verbal", "radio", "none", "unknown"],
        "language_barrier_present": bool,
        "heuristic_traps_observed": ["familiarity", "social_proof",
        "commitment", "expert_halo", "scarcity", "acceptance"],
        "fatigue_level": "low|moderate|high|unknown",
        "risk_tolerance_inferred": "low|moderate|high|unknown"
    },
    "rescue_and_outcome": {
        "rescue_delay_minutes_est": int,
        "self_rescue_attempted": bool,
        "survivor_condition_notes": string,
        "body_recovery_difficulty": "easy|moderate|technical|high|unknown",
        "remains_recovered": bool
    },
    "investigation_notes": {
        "investigation_in_progress": bool,
        "anchor_recovered": bool,
        "anchor_backup_found": bool,
        "gear_recovered_description": string,
        "uncertainties_list": [string]
    },
    "cause_classification": {
        "primary_cause_category": "technical_system_failure|environmental|
        human_factor|medical|unknown",
        "secondary_cause_categories": [string],
        "narrative_summary": string
    }
}
"""

_PROMPT = """
System: You are a precise information extraction assistant. Return VALID JSON
only, no prose, no markdown fences. Do NOT invent details.

SCHEMA:
{SCHEMA}

Guidance:
- Use ONLY evidence present in the provided PRE-EXTRACTED and ARTICLE text. If
  unsure, omit the key.
- Normalize dates to ISO format when possible; do not fabricate years.
- Keep arrays of strings concise and canonical (e.g., 'Squamish Search and
  Rescue', 'Sea to Sky RCMP').

PRE-EXTRACTED:
{PRE}

ARTICLE:
{ARTICLE}

Return one JSON object.
"""

__all__ = ["_SCHEMA_TEXT", "_PROMPT"]

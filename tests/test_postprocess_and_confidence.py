import sys
from pathlib import Path

import pytest

# Ensure repo root importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from accident_postprocess import _postprocess, compute_confidence


def test_postprocess_cleans_and_normalizes():
    raw = {
        'source_url': ' https://example.com/x ',
        'article_date_published': '2025-10-01Z',
        'num_people_involved': '3',
        'num_fatalities': '1',
        'num_rescued': 0.0,
        'people': [
            {'name': ' Jane Doe ', 'age': '34', 'outcome': ' Minor '},
            'ignore',
            {'name': '  ', 'age': 'x'},
        ],
        'photo_urls': 'https://img.example/x.jpg',
        'extraction_confidence_score': '2.0',  # invalid, should be dropped
        'accident_causes': {
            'proximate_causes': ['Rockfall', 'unknown', 'ICEFALL'],
            'contributing_factors': ['Route_Finding_Error', 'improper_knots', 'zzz'],
            'anchor_system': {
                'anchor_type': 'BOLT',
                'num_points': '2',
                'redundancy_present': True,
                'anchor_condition': 'Weathered',
                'failure_mode': 'Pulled',
            },
            'rope_system': {
                'num_people_on_rope': '2',
                'roped_for_descent': False,
                'rope_type': 'SINGLE',
                'belay_method': 'RAPPEL',
                'failure_description': ' Cut rope',
                'knots_used': ['overhand', ' figure 8 '],
            },
            'decision_factors': {
                'objective_hazard_awareness': 'HIGH',
                'time_pressure': True,
                'group_dynamics': 'Leader_Follower',
                'experience_level_est': 'Mixed',
                'weather_forecast_considered': False,
                'alternate_plan_available': True,
            },
            'environmental_conditions': {
                'weather_change_timing': 'During',
                'precipitation_intensity': 'Heavy',
                'temperature_trend': 'Cooling',
                'wind_speed_est': 'Strong',
                'snowpack_instability_signs': ['whumphing', ' shooting cracks '],
                'visibility_class': 'Poor',
            },
            'human_factors': {
                'group_size': '3',
                'group_experience_mix': 'homogeneous',
                'communication_method': ['radio', ' Radio '],
                'language_barrier_present': False,
                'heuristic_traps_observed': ['familiarity', 'commitment'],
                'fatigue_level': 'Moderate',
                'risk_tolerance_inferred': 'High',
            },
            'rescue_and_outcome': {
                'rescue_delay_minutes_est': '45',
                'self_rescue_attempted': True,
                'remains_recovered': False,
                'survivor_condition_notes': ' Hypothermia ',
                'body_recovery_difficulty': 'Technical',
            },
            'investigation_notes': {
                'investigation_in_progress': True,
                'anchor_recovered': False,
                'anchor_backup_found': True,
                'gear_recovered_description': ' slings ',
                'uncertainties_list': ['what failed?', ' anchor age '],
            },
            'cause_classification': {
                'primary_cause_category': 'Environmental',
                'secondary_cause_categories': ['HUMAN_FACTOR', 'medical'],
                'narrative_summary': ' brief ',
            },
        },
    }

    out = _postprocess(raw)
    # source_url trimmed
    assert out.get('source_url') == 'https://example.com/x'
    # date normalized to ISO (YYYY-MM-DD)
    assert out.get('article_date_published') == '2025-10-01'
    # numeric coercion and list cleaning
    assert out.get('num_people_involved') == 3
    assert out.get('num_fatalities') == 1
    assert out.get('num_rescued') == 0
    assert out.get('people') and out['people'][0]['name'] == 'Jane Doe'
    assert out['people'][0]['age'] == 34
    assert out.get('photo_urls') == ['https://img.example/x.jpg']
    # invalid confidence removed
    assert 'extraction_confidence_score' not in out

    causes = out.get('accident_causes')
    assert causes and 'proximate_causes' in causes
    # enums lowercased and filtered
    assert set(causes['proximate_causes']) <= {'rockfall', 'icefall'}
    assert 'contributing_factors' in causes
    assert 'route_finding_error' in causes['contributing_factors']
    # nested structures
    assert causes.get('anchor_system', {}).get('num_points') == 2
    assert causes.get('rope_system', {}).get('rope_type') == 'single'
    assert causes.get('decision_factors', {}).get('objective_hazard_awareness') == 'high'
    assert causes.get('environmental_conditions', {}).get('visibility_class') == 'poor'
    assert causes.get('human_factors', {}).get('group_size') == 3
    assert causes.get('rescue_and_outcome', {}).get('rescue_delay_minutes_est') == 45
    assert 'uncertainties_list' in causes.get('investigation_notes', {})
    assert causes.get('cause_classification', {}).get('primary_cause_category') == 'environmental'


def test_compute_confidence_components():
    pre = {
        'pre_dates': ['2025-10-01', '2024-01-01'],
        'gazetteer_matches': ['Mount Test'],
        'fall_height_feet_pre': '100',
        'num_fatalities_pre': '1',
        'people_pre': [{'age': 28}, {'age': 40}],
    }
    llm = {
        'accident_date': '2025-10-01',
        'mountain_name': 'Mount Test North',
        'fall_height_meters_estimate': 30.48,  # ~100ft
        'num_fatalities': 1,
        'people': [{'age': 28}, {'age': 33}],
    }
    s = compute_confidence(pre, llm)
    # Should accumulate several components (> 0)
    assert s > 0.5

    # No matches -> low score
    s2 = compute_confidence({}, {})
    assert s2 == 0.0

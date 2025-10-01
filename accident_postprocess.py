"""Post-processing and validation for accident info extraction."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

from accident_utils import _iso_or_none

logger = logging.getLogger(__name__)
try:
    logger.addHandler(logging.NullHandler())
except Exception:
    pass


def _postprocess(obj: dict) -> dict:
    expected = {
        'source_url': str,
        'source_name': str,
        'article_title': str,
        'article_date_published': str,
        'region': str,
        'mountain_name': str,
        'route_name': str,
        'activity_type': str,
        'accident_type': str,
        'accident_date': str,
        'accident_time_approx': str,
        'num_people_involved': int,
        'num_fatalities': int,
        'num_injured': int,
        'num_rescued': int,
        'people': list,
        'rescue_teams_involved': list,
        'response_agencies': list,
        'quoted_dialogue': list,
        'photo_urls': list,
        'video_urls': list,
        'related_articles_urls': list,
        'fundraising_links': list,
        'official_reports_links': list,
        'rescue_method': str,
        'response_difficulties': str,
        'bodies_recovery_method': str,
        'accident_summary_text': str,
        'timeline_text': str,
        'notable_equipment_details': str,
        'local_expert_commentary': str,
        'family_statements': str,
        'fall_height_meters_estimate': float,
        'self_rescue_boolean': bool,
        'anchor_failure_boolean': bool,
        'extraction_confidence_score': float,
        'accident_causes': dict,
    }

    out: dict = {}

    def keep_str(k, v):
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()

    def keep_int(k, v):
        if isinstance(v, int):
            out[k] = v
        elif isinstance(v, str):
            try:
                out[k] = int(v.strip())
            except Exception:
                pass
        elif isinstance(v, float):
            out[k] = int(v)

    def keep_float(k, v):
        if isinstance(v, (int, float)):
            out[k] = float(v)
        elif isinstance(v, str):
            try:
                out[k] = float(v.strip())
            except Exception:
                pass

    def keep_bool(k, v):
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, str):
            if v.strip().lower() in ('true', 'yes', '1'):
                out[k] = True
            elif v.strip().lower() in ('false', 'no', '0'):
                out[k] = False

    def keep_list_of_str(k, v):
        if isinstance(v, list):
            vals = [s.strip() for s in v if isinstance(s, str) and s.strip()]
            if vals:
                seen = set()
                uniq = []
                for s in vals:
                    if s not in seen:
                        seen.add(s)
                        uniq.append(s)
                out[k] = uniq
        elif isinstance(v, str) and v.strip():
            out[k] = [v.strip()]

    def _clean_list_str(vals):
        if isinstance(vals, list):
            return [s.strip() for s in vals if isinstance(s, str) and s.strip()]
        elif isinstance(vals, str) and vals.strip():
            return [vals.strip()]
        return []

    def _keep_enum(val, allowed):
        try:
            if isinstance(val, str) and val:
                v = val.strip().lower()
                if v in allowed:
                    return v
            return None
        except Exception:
            return None

    def _clean_causes(data: dict) -> dict:
        if not isinstance(data, dict):
            return {}
        outc: dict = {}
        allowed_prox = {
            "anchor_failure", "rope_system_failure", "fall_on_steep_snow",
            "rockfall", "icefall", "avalanche", "crevasse_fall",
            "weather_change", "visibility_loss", "cornice_collapse",
            "terrain_trap_involvement", "slip_or_trip", "miscommunication",
            "medical_emergency", "equipment_malfunction",
        }
        prox = _clean_list_str(data.get('proximate_causes'))
        prox = [p.lower() for p in prox if p.lower() in allowed_prox]
        if prox:
            seen = set()
            outc['proximate_causes'] = [p for p in prox if not (p in seen or seen.add(p))]

        allowed_contrib = {
            "single_point_anchor", "anchor_old_or_weathered",
            "no_anchor_backup", "overloaded_anchor", "party_all_on_one_rope",
            "no_fixed_protection", "improper_knots",
            "inadequate_edge_protection", "unroped_on_glacier",
            "late_in_day", "rapid_temperature_change", "storm_arrival",
            "wind_slab_loading", "poor_visibility",
            "human_factor_heuristic_trap", "route_finding_error", "fatigue",
            "equipment_left_in_place", "improvised_anchor",
            "technical_skill_mismatch",
        }
        contrib = _clean_list_str(data.get('contributing_factors'))
        contrib = [c.lower() for c in contrib if c.lower() in allowed_contrib]
        if contrib:
            seen = set()
            outc['contributing_factors'] = [c for c in contrib if not (c in seen or seen.add(c))]

        if isinstance(data.get('anchor_system'), dict):
            a = data['anchor_system']
            a_out = {}
            a_type = _keep_enum(a.get('anchor_type'), {
                'piton','bolt','gear_anchor','snow_picket','bollard','v-thread','tree','rock_horn','natural','unknown'
            })
            if a_type:
                a_out['anchor_type'] = a_type
            try:
                if isinstance(a.get('num_points'), (int, float, str)) and str(a.get('num_points')).strip():
                    a_out['num_points'] = int(float(str(a['num_points']).strip()))
            except Exception:
                pass
            if isinstance(a.get('redundancy_present'), bool):
                a_out['redundancy_present'] = a['redundancy_present']
            cond = _keep_enum(a.get('anchor_condition'), {'new','good','old','weathered','rusted','unknown'})
            if cond:
                a_out['anchor_condition'] = cond
            fail = _keep_enum(a.get('failure_mode'), {'pulled','snapped','sheared','unknown'})
            if fail:
                a_out['failure_mode'] = fail
            if a_out:
                outc['anchor_system'] = a_out

        if isinstance(data.get('rope_system'), dict):
            r = data['rope_system']
            r_out = {}
            try:
                if isinstance(r.get('num_people_on_rope'), (int, float, str)) and str(r.get('num_people_on_rope')).strip():
                    r_out['num_people_on_rope'] = int(float(str(r['num_people_on_rope']).strip()))
            except Exception:
                pass
            for bkey in ['roped_for_descent','roped_for_ascent','protection_in_place']:
                if isinstance(r.get(bkey), bool):
                    r_out[bkey] = r[bkey]
            r_type = _keep_enum(r.get('rope_type'), {'single','half','twin','static','unknown'})
            if r_type:
                r_out['rope_type'] = r_type
            belay = _keep_enum(r.get('belay_method'), {'rappel','lower','simul','pitch','running_belay','short_rope','unroped'})
            if belay:
                r_out['belay_method'] = belay
            if isinstance(r.get('failure_description'), str) and r.get('failure_description').strip():
                r_out['failure_description'] = r['failure_description'].strip()
            k = _clean_list_str(r.get('knots_used'))
            if k:
                r_out['knots_used'] = k
            if r_out:
                outc['rope_system'] = r_out

        if isinstance(data.get('decision_factors'), dict):
            d = data['decision_factors']
            d_out = {}
            oh = _keep_enum(d.get('objective_hazard_awareness'), {'low','medium','high','unknown'})
            if oh:
                d_out['objective_hazard_awareness'] = oh
            if isinstance(d.get('time_pressure'), bool):
                d_out['time_pressure'] = d['time_pressure']
            gd = _keep_enum(d.get('group_dynamics'), {'leader_follower','peer_pressure','independent','unknown'})
            if gd:
                d_out['group_dynamics'] = gd
            ex = _keep_enum(d.get('experience_level_est'), {'beginner','intermediate','advanced','expert','mixed','unknown'})
            if ex:
                d_out['experience_level_est'] = ex
            for bkey in ['weather_forecast_considered','alternate_plan_available']:
                if isinstance(d.get(bkey), bool):
                    d_out[bkey] = d[bkey]
            if d_out:
                outc['decision_factors'] = d_out

        if isinstance(data.get('equipment_status'), dict):
            e = data['equipment_status']
            e_out = {}
            for lkey in ['critical_gear_present','gear_condition_issues','missing_expected_gear','equipment_failure_noted']:
                vals = _clean_list_str(e.get(lkey))
                if vals:
                    e_out[lkey] = vals
            if e_out:
                outc['equipment_status'] = e_out

        if isinstance(data.get('environmental_conditions'), dict):
            env = data['environmental_conditions']
            env_out = {}
            wct = _keep_enum(env.get('weather_change_timing'), {'before','during','after','none','unknown'})
            if wct:
                env_out['weather_change_timing'] = wct
            pi = _keep_enum(env.get('precipitation_intensity'), {'none','light','moderate','heavy'})
            if pi:
                env_out['precipitation_intensity'] = pi
            tt = _keep_enum(env.get('temperature_trend'), {'warming','cooling','stable','unknown'})
            if tt:
                env_out['temperature_trend'] = tt
            wse = _keep_enum(env.get('wind_speed_est'), {'calm','moderate','strong','storm'})
            if wse:
                env_out['wind_speed_est'] = wse
            sps = _clean_list_str(env.get('snowpack_instability_signs'))
            if sps:
                env_out['snowpack_instability_signs'] = list(dict.fromkeys([s.lower() for s in sps]))
            vc = _keep_enum(env.get('visibility_class'), {'good','moderate','poor','whiteout'})
            if vc:
                env_out['visibility_class'] = vc
            if env_out:
                outc['environmental_conditions'] = env_out

        if isinstance(data.get('human_factors'), dict):
            hf = data['human_factors']
            hf_out = {}
            try:
                if isinstance(hf.get('group_size'), (int, float, str)) and str(hf.get('group_size')).strip():
                    hf_out['group_size'] = int(float(str(hf['group_size']).strip()))
            except Exception:
                pass
            gem = _keep_enum(hf.get('group_experience_mix'), {'homogeneous','mixed','unknown'})
            if gem:
                hf_out['group_experience_mix'] = gem
            cm = _clean_list_str(hf.get('communication_method'))
            if cm:
                hf_out['communication_method'] = list(dict.fromkeys([c.lower() for c in cm]))
            if isinstance(hf.get('language_barrier_present'), bool):
                hf_out['language_barrier_present'] = hf['language_barrier_present']
            ht = _clean_list_str(hf.get('heuristic_traps_observed'))
            if ht:
                hf_out['heuristic_traps_observed'] = list(dict.fromkeys([h.lower() for h in ht]))
            fl = _keep_enum(hf.get('fatigue_level'), {'low','moderate','high','unknown'})
            if fl:
                hf_out['fatigue_level'] = fl
            rti = _keep_enum(hf.get('risk_tolerance_inferred'), {'low','moderate','high','unknown'})
            if rti:
                hf_out['risk_tolerance_inferred'] = rti
            if hf_out:
                outc['human_factors'] = hf_out

        if isinstance(data.get('rescue_and_outcome'), dict):
            ro = data['rescue_and_outcome']
            ro_out = {}
            try:
                if isinstance(ro.get('rescue_delay_minutes_est'), (int, float, str)) and str(ro.get('rescue_delay_minutes_est')).strip():
                    ro_out['rescue_delay_minutes_est'] = int(float(str(ro['rescue_delay_minutes_est']).strip()))
            except Exception:
                pass
            for bkey in ['self_rescue_attempted','remains_recovered']:
                if isinstance(ro.get(bkey), bool):
                    ro_out[bkey] = ro[bkey]
            if isinstance(ro.get('survivor_condition_notes'), str) and ro['survivor_condition_notes'].strip():
                ro_out['survivor_condition_notes'] = ro['survivor_condition_notes'].strip()
            brd = _keep_enum(ro.get('body_recovery_difficulty'), {'easy','moderate','technical','high','unknown'})
            if brd:
                ro_out['body_recovery_difficulty'] = brd
            if ro_out:
                outc['rescue_and_outcome'] = ro_out

        if isinstance(data.get('investigation_notes'), dict):
            inv = data['investigation_notes']
            inv_out = {}
            for bkey in ['investigation_in_progress','anchor_recovered','anchor_backup_found']:
                if isinstance(inv.get(bkey), bool):
                    inv_out[bkey] = inv[bkey]
            if isinstance(inv.get('gear_recovered_description'), str) and inv['gear_recovered_description'].strip():
                inv_out['gear_recovered_description'] = inv['gear_recovered_description'].strip()
            ul = _clean_list_str(inv.get('uncertainties_list'))
            if ul:
                inv_out['uncertainties_list'] = ul
            if inv_out:
                outc['investigation_notes'] = inv_out

        if isinstance(data.get('cause_classification'), dict):
            cc = data['cause_classification']
            cc_out = {}
            p = _keep_enum(cc.get('primary_cause_category'), {'technical_system_failure','environmental','human_factor','medical','unknown'})
            if p:
                cc_out['primary_cause_category'] = p
            sc = _clean_list_str(cc.get('secondary_cause_categories'))
            if sc:
                cc_out['secondary_cause_categories'] = list(dict.fromkeys([s.lower() for s in sc]))
            if isinstance(cc.get('narrative_summary'), str) and cc['narrative_summary'].strip():
                cc_out['narrative_summary'] = cc['narrative_summary'].strip()
            if cc_out:
                outc['cause_classification'] = cc_out

        return outc

    for k, v in obj.items():
        if k not in expected:
            if isinstance(v, str) and v.strip():
                out[k] = v.strip()
            continue
        typ = expected[k]
        if typ is str:
            keep_str(k, v)
        elif typ is int:
            keep_int(k, v)
        elif typ is float:
            keep_float(k, v)
        elif typ is bool:
            keep_bool(k, v)
        elif typ is list:
            if k == 'people' and isinstance(v, list):
                people_out = []
                for person in v:
                    if not isinstance(person, dict):
                        continue
                    p = {}
                    if 'name' in person and isinstance(person['name'], str) and person['name'].strip():
                        p['name'] = person['name'].strip()
                    if 'age' in person:
                        try:
                            p['age'] = int(person['age'])
                        except Exception:
                            pass
                    if 'outcome' in person and isinstance(person['outcome'], str):
                        p['outcome'] = person['outcome'].strip()
                    if 'injuries' in person and isinstance(person['injuries'], str):
                        p['injuries'] = person['injuries'].strip()
                    if p:
                        people_out.append(p)
                if people_out:
                    out['people'] = people_out
            else:
                keep_list_of_str(k, v)
        elif typ is dict:
            if k == 'accident_causes':
                cleaned = _clean_causes(v)
                if cleaned:
                    out[k] = cleaned

    for dk in ('article_date_published', 'accident_date', 'missing_since', 'recovery_date'):
        if dk in out:
            iso = _iso_or_none(out[dk])
            if iso:
                out[dk] = iso
            else:
                out.pop(dk, None)

    if 'extraction_confidence_score' in out:
        try:
            v = float(out['extraction_confidence_score'])
            if 0.0 <= v <= 1.0:
                out['extraction_confidence_score'] = v
            else:
                out.pop('extraction_confidence_score', None)
        except Exception:
            out.pop('extraction_confidence_score', None)

    if out.get('num_fatalities') is not None and out.get('num_people_involved') is not None:
        if out['num_fatalities'] > out['num_people_involved']:
            logger.warning('⚠️  num_fatalities > num_people_involved; leaving values but check source')

    return out


def compute_confidence(pre: dict, llm: dict) -> float:
    score = 0.0
    try:
        pd = pre.get('pre_dates', [])
        for d in pd:
            iso = _iso_or_none(d)
            if iso and (llm.get('accident_date') == iso or llm.get('article_date_published') == iso):
                score += 0.25
                break
        if pre.get('gazetteer_matches'):
            g0 = pre['gazetteer_matches'][0]
            if llm.get('mountain_name') and g0.lower() in llm.get('mountain_name', '').lower():
                score += 0.2
        if 'fall_height_feet_pre' in pre and 'fall_height_meters_estimate' in llm:
            try:
                feet = float(pre['fall_height_feet_pre'])
                meters_est = float(llm['fall_height_meters_estimate'])
                meters_from_feet = feet * 0.3048
                if abs(meters_from_feet - meters_est) / max(meters_est, 1.0) < 0.15:
                    score += 0.2
            except Exception:
                pass
        if 'num_fatalities_pre' in pre and 'num_fatalities' in llm:
            try:
                if int(pre['num_fatalities_pre']) == int(llm['num_fatalities']):
                    score += 0.15
            except Exception:
                pass
        if 'people_pre' in pre and 'people' in llm:
            pre_people = pre['people_pre']
            ll_people = llm['people'] if isinstance(llm['people'], list) else []
            matches = 0
            for p in pre_people:
                for q in ll_people:
                    if 'age' in p and 'age' in q and int(p['age']) == int(q.get('age', -1)):
                        matches += 1
                        break
            if matches >= 1:
                score += 0.2
    except Exception:
        pass

    return min(1.0, round(score, 2))


__all__ = ["_postprocess", "compute_confidence"]

import re

import pytest
from pydantic import ValidationError

from seekhunter.settings_model import AppSettings, Weights

CITIZENSHIP_PHRASES = [
    "Applicants must be Australian citizens.",
    "Australian citizens required",
    "You must hold Australian citizenship",
    "Australian citizenship is a requirement",
    "Only open to Australian citizens",
    "Must have PR",
]


def test_defaults_contain_core_rules():
    s = AppSettings()
    assert "BAE Systems" in s.defence_employers
    assert "Westpac" in s.bank_employers
    assert any("NV1" in p for p in s.clearance_patterns)
    assert s.weights.flexible_work == 35
    assert s.weights.full_time == 10
    assert s.llm_providers == ["anthropic", "openclaw"]
    assert s.notify_cities == ["adelaide"]
    assert s.other_city_max_pages == 2
    assert s.notifications_read_at is None
    assert s.linkedin_enabled is True
    assert s.linkedin_max_pages == 2


def test_roundtrip_json():
    s = AppSettings()
    s.employer_allowlist.append("Acme")
    again = AppSettings.model_validate_json(s.model_dump_json())
    assert again.employer_allowlist == ["Acme"]


def test_notifications_read_at_roundtrips_through_json_mode_dump():
    from datetime import datetime

    s = AppSettings(notifications_read_at=datetime(2026, 1, 1, 12, 0, 0))
    again = AppSettings.model_validate(s.model_dump(mode="json"))
    assert again.notifications_read_at == datetime(2026, 1, 1, 12, 0, 0)


def test_citizenship_patterns_match_common_phrasings():
    s = AppSettings()
    for phrase in CITIZENSHIP_PHRASES:
        assert any(re.search(p, phrase, re.I) for p in s.citizenship_patterns), phrase


def test_clearance_patterns_match_nv_and_tspv_variants():
    s = AppSettings()
    assert any(re.search(p, "NV-1 clearance", re.I) for p in s.clearance_patterns)
    assert any(re.search(p, "TSPV", re.I) for p in s.clearance_patterns)


def test_invalid_regex_pattern_raises_validation_error():
    with pytest.raises(ValidationError):
        AppSettings(clearance_patterns=["("])


def test_overlong_regex_pattern_raises_validation_error():
    with pytest.raises(ValidationError):
        AppSettings(clearance_patterns=["a" * 201])


def test_regex_pattern_at_length_limit_is_accepted():
    s = AppSettings(clearance_patterns=["a" * 200])
    assert len(s.clearance_patterns[0]) == 200


NEW_CITIZENSHIP_PHRASES = [
    "Only Australian citizens will be considered",
    "Australian PR or citizenship required",
    "Must have permanent residency or citizenship",
    "(Citizen or PR)",
    "Applicants without Australian citizenship will not be considered",
]


def test_citizenship_patterns_match_additional_real_world_phrasings():
    s = AppSettings()
    for phrase in NEW_CITIZENSHIP_PHRASES:
        assert any(re.search(p, phrase, re.I) for p in s.citizenship_patterns), phrase


def test_default_weights_add_up_to_100_and_blend_defaults_to_old_mix():
    s = AppSettings()
    assert s.weights.rule_total() == 100 and s.weights.problems() == []
    assert s.rule_blend == 0.6


def test_stored_settings_without_rule_blend_or_with_odd_weights_still_load():
    stored = AppSettings().model_dump(mode="json")
    del stored["rule_blend"]
    stored["weights"] = {"flexible_work": 40, "full_time": 10, "skill_max": 50, "role_max": 30,
                         "skill_saturation": 8}
    s = AppSettings.model_validate(stored)
    assert s.rule_blend == 0.6
    assert s.weights.rule_total() == 120
    assert any("add up to 100" in p for p in s.weights.problems())


def test_weight_problems():
    assert Weights(flexible_work=10, full_time=35).problems() == []  # work type = the better of the two
    assert "weights.skill_saturation must be at least 1" in Weights(skill_saturation=0).problems()
    assert any("negative" in p for p in Weights(full_time=-5).problems())


def test_rule_blend_bounds():
    with pytest.raises(ValidationError):
        AppSettings(rule_blend=1.5)

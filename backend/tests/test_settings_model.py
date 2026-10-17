import re

import pytest
from pydantic import ValidationError

from seekhunter.settings_model import AppSettings

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

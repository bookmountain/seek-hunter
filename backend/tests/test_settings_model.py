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


def test_roundtrip_json():
    s = AppSettings()
    s.employer_allowlist.append("Acme")
    again = AppSettings.model_validate_json(s.model_dump_json())
    assert again.employer_allowlist == ["Acme"]


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

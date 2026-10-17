from seekhunter.settings_model import AppSettings


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

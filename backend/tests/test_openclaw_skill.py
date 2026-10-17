from pathlib import Path

SKILL_MD = (
    Path(__file__).parent.parent.parent / "openclaw-skill" / "seekhunter" / "SKILL.md"
)


def _text() -> str:
    return SKILL_MD.read_text()


def test_skill_md_exists():
    assert SKILL_MD.is_file()


def test_skill_md_documents_applied_patch():
    text = _text()
    assert "## Application history" in text
    assert """seekhunter-api PATCH /api/jobs/7 '{"status":"applied"}'""" in text


def test_skill_md_documents_manual_application_creation():
    text = _text()
    assert "seekhunter-api POST /api/applications" in text
    assert '"company":"<Company>"' in text
    assert '"contact":{"name"' in text


def test_skill_md_documents_application_stage_patch():
    text = _text()
    assert "seekhunter-api PATCH /api/applications/{id}" in text
    assert '"stage":"interview"' in text
    assert "applied" in text and "screening" in text and "no_response" in text


def test_skill_md_documents_contact_lookup_before_logging_interaction():
    text = _text()
    assert 'seekhunter-api GET "/api/contacts?q=Brayden"' in text
    assert "seekhunter-api POST /api/interactions" in text
    assert "ask Book which contact" in text


def test_skill_md_documents_contact_log_convenience_endpoint():
    assert "seekhunter-api POST /api/jobs/7/contact-log" in _text()


def test_skill_md_documents_history_summary_for_pipeline_questions():
    text = _text()
    assert 'seekhunter-api GET "/api/history/summary?days=14"' in text
    assert "follow-ups due" in text


def test_skill_md_documents_companies_lookup():
    assert 'seekhunter-api GET "/api/companies?q=<Company>"' in _text()


def test_skill_md_documents_city_filter_on_jobs():
    text = _text()
    assert 'seekhunter-api GET "/api/jobs?city=melbourne"' in text
    assert 'seekhunter-api GET "/api/jobs/cities?view=active"' in text


def test_skill_md_documents_enabling_city_notifications():
    text = _text()
    assert "notify_cities" in text
    assert "enable Melbourne notifications" in text
    assert "GET /api/settings" in text
    assert "PUT /api/settings" in text

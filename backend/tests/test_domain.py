from seekhunter.domain import JobData, dedupe_key, html_to_text, normalize_work_type


def test_normalize_work_type():
    assert normalize_work_type("Part time") == "part_time"
    assert normalize_work_type("Contract/Temp") == "contract"
    assert normalize_work_type("Casual/Vacation") == "casual"
    assert normalize_work_type("Full time, Permanent") == "full_time"
    assert normalize_work_type("Temporary") == "contract"
    assert normalize_work_type("") == "unknown"
    assert normalize_work_type(None) == "unknown"


def test_html_to_text_collapses_whitespace():
    assert html_to_text("<p>Hello</p>\n<ul><li>React</li><li>C#</li></ul>") == "Hello React C#"
    assert html_to_text("") == ""


def test_dedupe_key_normalizes_company_suffixes():
    a = dedupe_key("Full Stack Developer", "Acme Pty Ltd")
    b = dedupe_key("Full-Stack  Developer", "ACME")
    assert a == b


def test_jobdata_text_prefers_description():
    job = JobData(source="seek", external_id="1", title="Dev", company="A", location="Adelaide SA",
                  work_type="part_time", url="u", teaser="short", description_html="<p>Long text</p>")
    assert job.text == "Long text"
    job2 = JobData(source="seek", external_id="2", title="Dev", company="A", location="",
                   work_type="unknown", url="u", teaser="short")
    assert job2.text == "short"

from seekhunter.domain import (
    JobData,
    company_key,
    dedupe_key,
    derive_city,
    derive_city_from_location,
    html_to_lines,
    html_to_text,
    normalize_work_type,
)


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


def test_html_to_lines_splits_list_items_and_drops_blanks():
    html = "<ul><li>No visa sponsorship</li><li>Security clearance required</li></ul>"
    assert html_to_lines(html) == "No visa sponsorship\nSecurity clearance required"
    assert html_to_lines("") == ""


def test_jobdata_filter_text_uses_lines_and_falls_back_to_teaser():
    html = "<li>Hybrid, no weekends</li><li>NV1 clearance required</li>"
    job = JobData(source="seek", external_id="1", title="Dev", company="A", location="Adelaide SA",
                  work_type="part_time", url="u", teaser="short", description_html=html)
    assert job.filter_text == "Hybrid, no weekends\nNV1 clearance required"
    job2 = JobData(source="seek", external_id="2", title="Dev", company="A", location="",
                   work_type="unknown", url="u", teaser="short")
    assert job2.filter_text == "short"


def test_dedupe_key_strips_state_suffix():
    key = dedupe_key("Azure Cloud Developer", "Peoplebank Australia SA")
    assert key == dedupe_key("Azure Cloud Developer", "Peoplebank")


def test_company_key_normalizes_suffixes_and_punctuation():
    assert company_key("Acme Pty Ltd") == company_key("ACME")
    assert company_key("Robert Walters Australia") == company_key("Robert Walters")
    assert company_key("") == ""
    assert company_key(None) == ""


def test_dedupe_key_reuses_company_key():
    assert dedupe_key("Dev", "Acme Pty Ltd") == f"dev|{company_key('Acme Pty Ltd')}"


def test_derive_city_from_profile_location():
    assert derive_city("All Adelaide SA", "whatever") == "adelaide"
    assert derive_city("All Melbourne VIC", "whatever") == "melbourne"
    assert derive_city("All Sydney NSW", "whatever") == "sydney"
    assert derive_city("All Perth WA", "whatever") == "perth"
    assert derive_city("All Brisbane QLD", "whatever") == "brisbane"


def test_derive_city_falls_back_to_job_location_when_profile_unknown():
    assert derive_city(None, "Adelaide SA") == "adelaide"
    assert derive_city("Some other search", "Sydney NSW") == "sydney"


def test_derive_city_defaults_to_other_when_nothing_matches():
    assert derive_city(None, "Remote") == "other"
    assert derive_city(None, "") == "other"


def test_derive_city_from_location_matches_known_cities_case_insensitively():
    assert derive_city_from_location("ADELAIDE SA") == "adelaide"
    assert derive_city_from_location("Melbourne VIC") == "melbourne"
    assert derive_city_from_location("somewhere else") == "other"
    assert derive_city_from_location(None) == "other"
    assert derive_city_from_location(None, default="adelaide") == "adelaide"
    assert derive_city_from_location("Remote", default="adelaide") == "adelaide"

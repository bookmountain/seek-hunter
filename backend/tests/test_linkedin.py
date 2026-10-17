from datetime import datetime

from seekhunter.models import SearchProfile
from seekhunter.sources.linkedin import (
    LinkedInSource,
    parse_applicant_count,
    parse_detail_html,
    parse_search_html,
)


def test_parse_search_html(fixtures_dir):
    jobs = parse_search_html((fixtures_dir / "linkedin_search.html").read_text())
    assert len(jobs) == 5

    first = jobs[0]
    assert first.source == "linkedin"
    assert first.external_id == "4468780007"
    assert first.title == "Software Engineer"
    assert first.company == "UpGuard"
    assert first.location == "Adelaide, South Australia, Australia"
    assert first.url == "https://www.linkedin.com/jobs/view/4468780007/"
    assert first.work_type == "unknown"  # not known until details()
    assert first.listed_at == datetime(2026, 10, 13)

    # "--new" variant of the listdate class (posted today) is parsed the same way.
    new_job = next(j for j in jobs if j.external_id == "4479801660")
    assert new_job.company == "Chrysos Corporation"
    assert new_job.listed_at == datetime(2026, 10, 17)


def test_parse_search_html_skips_cards_without_a_job_urn():
    html = """
    <div class="base-search-card">
      <h3 class="base-search-card__title">No urn</h3>
    </div>
    """
    assert parse_search_html(html) == []


def test_parse_applicant_count():
    assert parse_applicant_count("Over 200 applicants") == 200
    assert parse_applicant_count("34 applicants") == 34
    assert parse_applicant_count("") is None
    assert parse_applicant_count(None) is None


def test_parse_detail_html(fixtures_dir):
    desc, work_type, applicant_count = parse_detail_html((fixtures_dir / "linkedin_detail.html").read_text())
    assert "UpGuard" in desc
    assert work_type == "full_time"
    assert applicant_count == 200


def test_parse_detail_html_missing_sections_degrades_gracefully():
    desc, work_type, applicant_count = parse_detail_html("<html><body>nothing here</body></html>")
    assert desc == ""
    assert work_type == "unknown"
    assert applicant_count is None


class FakeResp:
    def __init__(self, text):
        self.text, self.status_code = text, 200


class FakeClient:
    def __init__(self, text):
        self.text, self.calls = text, []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return FakeResp(self.text)


def test_search_maps_location_and_date_filter(fixtures_dir):
    client = FakeClient((fixtures_dir / "linkedin_search.html").read_text())
    LinkedInSource(client).search(
        SearchProfile(name="t", keywords="software engineer", location="All Adelaide SA", work_types=[]),
        max_pages=1)
    params = client.calls[0][1]["params"]
    assert params["keywords"] == "software engineer"
    assert params["location"] == "Adelaide, South Australia, Australia"
    assert params["f_TPR"] == "r604800"
    assert params["start"] == 0
    assert "f_JT" not in params


def test_search_maps_unknown_location_by_stripping_all_prefix(fixtures_dir):
    client = FakeClient((fixtures_dir / "linkedin_search.html").read_text())
    LinkedInSource(client).search(
        SearchProfile(name="t", keywords="dev", location="All Darwin NT", work_types=[]), max_pages=1)
    assert client.calls[0][1]["params"]["location"] == "Darwin NT"


def test_search_maps_work_types_to_f_jt(fixtures_dir):
    client = FakeClient((fixtures_dir / "linkedin_search.html").read_text())
    LinkedInSource(client).search(
        SearchProfile(name="t", keywords="dev", location="All Adelaide SA",
                     work_types=["full_time", "contract", "casual"]),
        max_pages=1)
    assert client.calls[0][1]["params"]["f_JT"] == "C,F,T"


def test_search_paginates_by_offsetting_the_number_of_cards_returned(fixtures_dir):
    html = (fixtures_dir / "linkedin_search.html").read_text()
    client = FakeClient(html)
    jobs = LinkedInSource(client).search(
        SearchProfile(name="t", keywords="dev", location="All Adelaide SA", work_types=[]), max_pages=2)
    assert len(client.calls) == 2
    assert client.calls[0][1]["params"]["start"] == 0
    assert client.calls[1][1]["params"]["start"] == 5
    assert len(jobs) == 10


def test_search_stops_when_a_page_returns_no_cards():
    client = FakeClient("<html></html>")
    jobs = LinkedInSource(client).search(
        SearchProfile(name="t", keywords="dev", location="All Adelaide SA", work_types=[]), max_pages=3)
    assert jobs == []
    assert len(client.calls) == 1


def test_details_fills_description_work_type_and_applicant_count(fixtures_dir):
    from seekhunter.domain import JobData

    client = FakeClient((fixtures_dir / "linkedin_detail.html").read_text())
    job = JobData(source="linkedin", external_id="4468780007", title="Software Engineer", company="UpGuard",
                 location="Adelaide, South Australia, Australia", work_type="unknown",
                 url="https://www.linkedin.com/jobs/view/4468780007/")
    result = LinkedInSource(client).details(job)
    assert "UpGuard" in result.description_html
    assert result.work_type == "full_time"
    assert result.applicant_count == 200
    assert result.applicant_volume is None
    assert client.calls[0][0] == "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4468780007"

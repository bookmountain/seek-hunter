import math
from datetime import date, datetime

import pandas as pd
import pytest

from seekhunter.http import SourceBlocked
from seekhunter.models import SearchProfile
from seekhunter.sources.indeed import IndeedSource, indeed_location, parse_row, salary_label

NAN = math.nan


def row(**kw):
    base = {
        "id": "in-0ac3a8df7c590be9", "site": "indeed",
        "job_url": "https://au.indeed.com/viewjob?jk=0ac3a8df7c590be9", "job_url_direct": NAN,
        "title": "Software Engineer", "company": "Stratco", "location": "Gepps Cross, SA, Australia",
        "date_posted": date(2026, 11, 11), "job_type": NAN, "interval": NAN, "min_amount": NAN,
        "max_amount": NAN, "currency": NAN, "emails": NAN, "description": "<p>React TypeScript</p>",
    }
    base.update(kw)
    return base


def test_parse_row_maps_jobspy_columns():
    job = parse_row(row(job_type="contract", interval="hourly", min_amount=90.0, max_amount=110.0,
                        currency="AUD", emails="jane@stratco.com.au"))
    assert job.source == "indeed"
    assert job.external_id == "0ac3a8df7c590be9"
    assert job.title == "Software Engineer"
    assert job.company == "Stratco"
    assert job.location == "Gepps Cross SA"
    assert job.work_type == "contract"
    assert job.url == "https://au.indeed.com/viewjob?jk=0ac3a8df7c590be9"
    assert job.listed_at == datetime(2026, 11, 11)
    assert job.description_html == "<p>React TypeScript</p>"
    assert job.salary_label == "$90 – $110 per hour"
    assert job.contact_email == "jane@stratco.com.au"


def test_parse_row_handles_missing_values():
    job = parse_row(row(company=NAN, location="SA, Australia", date_posted=NAN, description=NAN))
    assert job.company == ""
    assert job.location == "SA"
    assert job.work_type == "unknown"
    assert job.listed_at is None
    assert job.description_html == ""
    assert job.salary_label is None
    assert job.contact_email is None


@pytest.mark.parametrize("job_type,expected", [
    ("fulltime", "full_time"), ("parttime", "part_time"), ("contract", "contract"),
    ("temporary", "contract"), ("parttime, contract", "part_time"), ("internship", "unknown"),
])
def test_work_type_mapping(job_type, expected):
    assert parse_row(row(job_type=job_type)).work_type == expected


def test_parse_row_without_id_hashes_the_url():
    job = parse_row(row(id=NAN))
    assert job.external_id and len(job.external_id) == 16


def test_salary_label_shapes():
    assert salary_label(116089.0, 125490.0, "yearly") == "$116,089 – $125,490 per year"
    assert salary_label(80000.0, None, "yearly") == "$80,000 per year"
    assert salary_label(None, None, "yearly") is None


def test_indeed_location_from_profile():
    assert indeed_location("All Adelaide SA") == "Adelaide, SA"
    assert indeed_location("All Melbourne VIC") == "Melbourne, VIC"
    assert indeed_location("Darwin") == "Darwin"


class FakeScrape:
    def __init__(self, df=None, exc=None):
        self.df, self.exc, self.calls = df, exc, []

    def __call__(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return self.df


def test_search_calls_jobspy_with_au_settings_and_maps_rows():
    df = pd.DataFrame([row(), row(id="in-2", job_url="https://au.indeed.com/viewjob?jk=2", title="Dev")])
    df.attrs = {"errors": {}, "warnings": {}}
    scrape = FakeScrape(df)
    src = IndeedSource(scrape=scrape, sleep=lambda s: None)
    profile = SearchProfile(name="p", keywords="developer", location="All Adelaide SA",
                            work_types=["contract"])
    jobs = src.search(profile, max_pages=2)
    assert [j.external_id for j in jobs] == ["0ac3a8df7c590be9", "2"]
    kw = scrape.calls[0]
    assert kw["site_name"] == ["indeed"]
    assert kw["search_term"] == "developer"
    assert kw["location"] == "Adelaide, SA"
    assert kw["country_indeed"] == "australia"
    assert kw["hours_old"] == 168
    assert kw["results_wanted"] == 50
    assert kw["job_type"] == "contract"
    assert kw["description_format"] == "html"
    assert src.client.request_count == 1


def test_search_drops_other_work_types_when_profile_has_several():
    df = pd.DataFrame([row(job_type="fulltime"), row(id="in-2", job_type="parttime"), row(id="in-3")])
    df.attrs = {"errors": {}}
    scrape = FakeScrape(df)
    src = IndeedSource(scrape=scrape, sleep=lambda s: None)
    profile = SearchProfile(name="p", keywords="dev", work_types=["part_time", "casual"])
    jobs = src.search(profile, max_pages=1)
    assert "job_type" not in scrape.calls[0]
    assert [j.external_id for j in jobs] == ["2", "3"]  # unknown type is kept


def test_search_errors_become_source_blocked():
    src = IndeedSource(scrape=FakeScrape(exc=RuntimeError("403 Forbidden")), sleep=lambda s: None)
    with pytest.raises(SourceBlocked):
        src.search(SearchProfile(name="p", keywords="dev"), 1)
    df = pd.DataFrame([])
    df.attrs = {"errors": {"indeed": "blocked by cloudflare"}}
    src = IndeedSource(scrape=FakeScrape(df), sleep=lambda s: None)
    with pytest.raises(SourceBlocked, match="cloudflare"):
        src.search(SearchProfile(name="p", keywords="dev"), 1)


def test_details_is_a_no_op():
    src = IndeedSource(scrape=FakeScrape(), sleep=lambda s: None)
    job = parse_row(row())
    assert src.details(job) is job

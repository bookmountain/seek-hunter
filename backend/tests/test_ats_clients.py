import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from seekhunter.sources.ats import ATSError, build_ats_clients, is_australian
from seekhunter.sources.ats.workday import parse_posted_on, parse_token

ATS = Path(__file__).parent / "fixtures" / "ats"


def load(name):
    return json.loads((ATS / name).read_text())


@dataclass
class Co:
    name: str
    ats_token: str | None


class Resp:
    def __init__(self, payload=None, status=200, text=None):
        self.payload, self.status_code = payload, status
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if self.payload is None:
            raise ValueError("not json")
        return self.payload


class FakeHTTP:
    """Routes (method, url-prefix) -> Resp; records calls."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def _match(self, method, url, kw):
        self.calls.append((method, url, kw))
        for (m, prefix), resp in self.routes.items():
            if m == method and url.startswith(prefix):
                return resp(kw) if callable(resp) else resp
        return Resp(None, 404, "not found")

    def get(self, url, **kw):
        return self._match("GET", url, kw)

    def post(self, url, **kw):
        return self._match("POST", url, kw)


@pytest.mark.parametrize("loc,expected", [
    ("Sydney", True), ("AU - Melbourne", True), ("Adelaide, South Australia", True),
    ("Australia (Flexible)", True), ("Remote - ANZ", True), ("Brisbane QLD", True),
    ("Perth, Scotland", False), ("Melbourne, FL", False), ("New York City", False),
    ("Chicago, IL", False), ("Bengaluru, Karnataka", False), ("", False), ("Seattle, WA", False),
])
def test_is_australian(loc, expected):
    assert is_australian(loc) is expected


def test_greenhouse_maps_board_jobs():
    http = FakeHTTP({("GET", "https://boards-api.greenhouse.io/v1/boards/cultureamp/jobs"):
                     Resp(load("greenhouse_cultureamp.json"))})
    jobs = build_ats_clients(http)["greenhouse"].list_jobs(Co("Culture Amp", "cultureamp"))
    assert http.calls[0][2]["params"] == {"content": "true"}
    assert len(jobs) == 4
    j = jobs[0]
    assert j.source == "radar"
    assert j.external_id.startswith("greenhouse:")
    assert j.title == "People and Systems Analyst"
    assert j.company == "Culture Amp"
    assert j.location == "Melbourne"
    assert j.url.startswith("https://job-boards.greenhouse.io/cultureamp/jobs/")
    assert j.listed_at is not None
    assert j.description_html.startswith("<")  # entity-escaped HTML is unescaped
    assert [x.location for x in jobs] == ["Melbourne", "Sydney", "Chicago", "Melbourne"]


def test_greenhouse_unknown_board_raises():
    with pytest.raises(ATSError):
        build_ats_clients(FakeHTTP({}))["greenhouse"].list_jobs(Co("Nope", "nope"))


def test_ats_client_without_token_raises():
    with pytest.raises(ATSError, match="no board token"):
        build_ats_clients(FakeHTTP({}))["lever"].list_jobs(Co("Nope", None))


def test_lever_maps_postings_with_country_and_lists():
    http = FakeHTTP({("GET", "https://api.lever.co/v0/postings/immutable"):
                     Resp(load("lever_immutable.json"))})
    jobs = build_ats_clients(http)["lever"].list_jobs(Co("Immutable", "immutable"))
    assert http.calls[0][2]["params"] == {"mode": "json"}
    by_title = {j.title: j for j in jobs}
    sec = by_title["Senior Security Engineer (Product Security)"]
    assert sec.external_id.startswith("lever:")
    assert sec.location == "Sydney"
    assert sec.url.startswith("https://jobs.lever.co/immutable/")
    assert sec.work_type == "full_time"  # "Full Time Permanent"
    assert "<h3>" in sec.description_html
    assert by_title["Customer Growth Lead"].location == "AMER"


def test_ashby_maps_board_and_prefers_australian_locations():
    http = FakeHTTP({("GET", "https://api.ashbyhq.com/posting-api/job-board/airwallex"):
                     Resp(load("ashby_airwallex.json"))})
    jobs = build_ats_clients(http)["ashby"].list_jobs(Co("Airwallex", "airwallex"))
    assert http.calls[0][2]["params"] == {"includeCompensation": "true"}
    assert len(jobs) == 4
    first = jobs[0]
    assert first.external_id.startswith("ashby:")
    assert first.title == "Staff Corporate Security Engineer"
    assert is_australian(first.location) and "Melbourne" in first.location
    assert first.work_type == "full_time"
    assert first.url.startswith("https://jobs.ashbyhq.com/airwallex/")
    assert first.description_html
    toronto = jobs[-1]
    assert not is_australian(toronto.location)
    assert toronto.salary_label and "CA$" in toronto.salary_label


def test_workable_pages_through_results_and_fetches_details():
    pages = [load("workable_rokt_page1.json"), load("workable_rokt_page2.json")]

    def listing(kw):
        return Resp(pages[1] if kw["json"].get("token") else pages[0])

    http = FakeHTTP({
        ("POST", "https://apply.workable.com/api/v3/accounts/rokt/jobs"): listing,
        ("GET", "https://apply.workable.com/api/v2/accounts/rokt/jobs/78589A4D7B"):
            Resp(load("workable_rokt_detail.json")),
    })
    client = build_ats_clients(http)["workable"]
    jobs = client.list_jobs(Co("Rokt", "rokt"))
    assert len(jobs) == 11
    assert http.calls[1][2]["json"]["token"] == pages[0]["nextPage"]
    sydney = next(j for j in jobs if j.external_id == "workable:78589A4D7B")
    assert sydney.location == "Sydney NSW, Australia"
    assert sydney.url == "https://apply.workable.com/rokt/j/78589A4D7B/"
    assert sydney.work_type == "full_time"
    assert sydney.description_html == ""
    detailed = client.details(sydney)
    assert "Rokt" in detailed.description_html and "<h3>Requirements</h3>" in detailed.description_html


def test_smartrecruiters_lists_au_postings_and_fetches_details():
    listing = load("smartrecruiters_canva.json")
    detail = load("smartrecruiters_canva_detail.json")
    http = FakeHTTP({
        ("GET", f"https://api.smartrecruiters.com/v1/companies/Canva/postings/{detail['id']}"): Resp(detail),
        ("GET", "https://api.smartrecruiters.com/v1/companies/canva/postings"): Resp(listing),
    })
    client = build_ats_clients(http)["smartrecruiters"]
    jobs = client.list_jobs(Co("Canva", "canva"))
    assert http.calls[0][2]["params"]["country"] == "au"
    assert len(jobs) == 4
    j = next(x for x in jobs if x.external_id == f"smartrecruiters:{detail['id']}")
    assert j.title.strip() == "Enterprise Security Manager"
    assert is_australian(j.location)
    assert j.work_type == "full_time"
    d = client.details(j)
    assert "Security Group" in d.description_html
    assert d.url == detail["postingUrl"]


def test_workday_lists_then_details_fill_location_and_body():
    listing = {**load("workday_telstra.json"), "total": 20}  # one page
    detail = load("workday_telstra_detail.json")
    api = "https://telstra.wd3.myworkdayjobs.com/wday/cxs/telstra/Telstra_Careers"
    http = FakeHTTP({
        ("POST", f"{api}/jobs"): Resp(listing),
        ("GET", f"{api}/job/Australia-Flexible/SRE-Engineer_JR-10176306"): Resp(detail),
    })
    client = build_ats_clients(http)["workday"]
    jobs = client.list_jobs(Co("Telstra", "telstra.wd3/Telstra_Careers"))
    method, url, kw = http.calls[0]
    assert (method, url) == ("POST", f"{api}/jobs")
    assert kw["json"] == {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}
    assert len(jobs) == 20
    sre = next(j for j in jobs if j.title == "SRE Engineer")
    assert sre.external_id == "workday:telstra:SRE-Engineer_JR-10176306"
    assert sre.url == "https://telstra.wd3.myworkdayjobs.com/Telstra_Careers/job/Australia-Flexible/SRE-Engineer_JR-10176306"
    assert sre.listed_at is not None
    d = client.details(sre)
    assert d.description_html
    assert d.location == "Australia (Flexible)"
    assert d.work_type == "full_time"


def test_workday_pages_until_total():
    calls = []

    def listing(kw):
        calls.append(kw["json"]["offset"])
        total = 45 if kw["json"]["offset"] == 0 else 0  # Workday only reports it on page one
        start = kw["json"]["offset"]
        return Resp({"total": total, "jobPostings": [
            {"title": f"Dev {start + i}", "externalPath": f"/job/x/Dev_{start + i}",
             "locationsText": "Adelaide", "postedOn": "Posted 3 Days Ago"} for i in range(20)]})

    http = FakeHTTP({("POST", "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Ext/jobs"): listing})
    jobs = build_ats_clients(http)["workday"].list_jobs(Co("Acme", "acme.wd5/Ext"))
    assert calls == [0, 20, 40]
    assert len(jobs) == 60


def test_workday_token_and_posted_on():
    assert parse_token("telstra.wd3/Telstra_Careers") == ("telstra", "wd3", "Telstra_Careers")
    with pytest.raises(ATSError):
        parse_token("telstra")
    from datetime import datetime, timedelta
    now = datetime(2026, 11, 12, 10)
    assert parse_posted_on("Posted Today", now) == now
    assert parse_posted_on("Posted Yesterday", now) == now - timedelta(days=1)
    assert parse_posted_on("Posted 30+ Days Ago", now) == now - timedelta(days=30)
    assert parse_posted_on("", now) is None

import json

from seekhunter.models import SearchProfile
from seekhunter.sources.seek import SeekSource, parse_search_item


class FakeResp:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, search, details):
        self.search, self.details, self.calls = search, details, []

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return FakeResp(self.search)

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return FakeResp(self.details)


def test_parse_search_item(fixtures_dir):
    item = json.loads((fixtures_dir / "seek_search.json").read_text())["data"][0]
    job = parse_search_item(item)
    assert job.source == "seek"
    assert job.external_id == "95229403"
    assert job.company == "Virginia Nursery"
    assert job.work_type == "part_time"
    assert job.location == "Virginia, Adelaide SA"
    assert job.url == "https://www.seek.com.au/job/95229403"
    assert job.listed_at is not None
    assert "Microsoft Access" in job.teaser


def test_search_builds_params_and_stops_at_total(fixtures_dir):
    payload = json.loads((fixtures_dir / "seek_search.json").read_text())
    payload["totalCount"] = 5
    client = FakeClient(payload, {})
    src = SeekSource(client)
    jobs = src.search(SearchProfile(name="t", keywords="developer", location="All Adelaide SA",
                                    work_types=["part_time", "contract"]), max_pages=3)
    assert len(jobs) == 5
    assert len(client.calls) == 1
    params = client.calls[0][2]["params"]
    assert params["where"] == "All Adelaide SA"
    assert params["worktype"] == "243,244"
    assert params["daterange"] == 7


def test_details_fills_description(fixtures_dir):
    item = json.loads((fixtures_dir / "seek_search.json").read_text())["data"][0]
    details = json.loads((fixtures_dir / "seek_details.json").read_text())
    src = SeekSource(FakeClient({}, details))
    job = src.details(parse_search_item(item))
    assert "Virginia Nursery Pty Ltd" in job.description_html

import json

import pytest

from seekhunter.http import SourceBlocked
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


def test_parse_search_item_empty_locations():
    job = parse_search_item({"id": "1", "title": "Dev", "locations": []})
    assert job.location == ""


def test_search_skips_items_without_id(fixtures_dir):
    payload = json.loads((fixtures_dir / "seek_search.json").read_text())
    item = payload["data"][0]
    no_id_item = dict(item)
    del no_id_item["id"]
    payload["data"] = [no_id_item, item]
    payload["totalCount"] = 2
    client = FakeClient(payload, {})
    jobs = SeekSource(client).search(
        SearchProfile(name="t", keywords="developer", location="All Adelaide SA", work_types=[]), max_pages=1)
    assert len(jobs) == 1


def test_search_stops_on_empty_page(fixtures_dir):
    payload = json.loads((fixtures_dir / "seek_search.json").read_text())
    payload["totalCount"] = 1000
    payload["data"] = []
    client = FakeClient(payload, {})
    jobs = SeekSource(client).search(
        SearchProfile(name="t", keywords="developer", location="All Adelaide SA", work_types=[]), max_pages=3)
    assert jobs == []
    assert len(client.calls) == 1


class BadJsonResp:
    status_code = 200

    def json(self):
        raise ValueError("bad json")


class BadJsonClient:
    def __init__(self):
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return BadJsonResp()

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return BadJsonResp()


def test_search_raises_source_blocked_on_non_json():
    profile = SearchProfile(name="t", keywords="developer", location="All Adelaide SA", work_types=[])
    with pytest.raises(SourceBlocked):
        SeekSource(BadJsonClient()).search(profile, max_pages=1)


def test_details_raises_source_blocked_on_non_json(fixtures_dir):
    item = json.loads((fixtures_dir / "seek_search.json").read_text())["data"][0]
    with pytest.raises(SourceBlocked):
        SeekSource(BadJsonClient()).details(parse_search_item(item))


def test_details_fills_contact_phone_and_email_from_contact_matches(fixtures_dir):
    item = json.loads((fixtures_dir / "seek_search.json").read_text())["data"][0]
    payload = {
        "data": {
            "jobDetails": {
                "job": {
                    "id": "95229403",
                    "content": "<p>Some ad text</p>",
                    "contactMatches": [
                        {"type": "Phone", "value": "08 8216 3534"},
                        {"type": "Email", "value": "jobs@virginianursery.com.au"},
                    ],
                }
            }
        }
    }
    src = SeekSource(FakeClient({}, payload))
    job = src.details(parse_search_item(item))
    assert job.contact_phone == "08 8216 3534"
    assert job.contact_email == "jobs@virginianursery.com.au"
    assert job.description_html == "<p>Some ad text</p>"


def test_details_without_contact_matches_leaves_contacts_none(fixtures_dir):
    item = json.loads((fixtures_dir / "seek_search.json").read_text())["data"][0]
    details = json.loads((fixtures_dir / "seek_details.json").read_text())
    src = SeekSource(FakeClient({}, details))
    job = src.details(parse_search_item(item))
    assert job.contact_phone is None
    assert job.contact_email is None


def test_details_uses_first_phone_and_email_when_multiple_present(fixtures_dir):
    item = json.loads((fixtures_dir / "seek_search.json").read_text())["data"][0]
    payload = {
        "data": {
            "jobDetails": {
                "job": {
                    "id": "95229403",
                    "content": "<p>ad</p>",
                    "contactMatches": [
                        {"type": "Phone", "value": "08 8216 3534"},
                        {"type": "Phone", "value": "0412 345 678"},
                        {"type": "Email", "value": "first@example.com"},
                        {"type": "Email", "value": "second@example.com"},
                    ],
                }
            }
        }
    }
    src = SeekSource(FakeClient({}, payload))
    job = src.details(parse_search_item(item))
    assert job.contact_phone == "08 8216 3534"
    assert job.contact_email == "first@example.com"


def test_details_returns_job_unchanged_on_errors(fixtures_dir):
    item = json.loads((fixtures_dir / "seek_search.json").read_text())["data"][0]
    job = parse_search_item(item)
    src = SeekSource(FakeClient({}, {"errors": [{"message": "boom"}]}))
    result = src.details(job)
    assert result == job

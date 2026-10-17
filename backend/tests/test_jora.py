from datetime import datetime, timedelta

from seekhunter.models import SearchProfile
from seekhunter.sources.jora import JoraSource, parse_detail_html, parse_posted, parse_search_html

NOW = datetime(2026, 10, 17, 12, 0)


def test_parse_search_html(fixtures_dir):
    jobs, has_next = parse_search_html((fixtures_dir / "jora_search.html").read_text(), NOW)
    assert has_next
    assert len(jobs) == 5
    first = jobs[0]
    assert first.source == "jora"
    assert first.external_id == "0df32b6e859d734ba88f1b03a73a7b3d"
    assert first.title == "Developer Programmer - SA"
    assert first.company == "PHILLIP RILEY PROJECTS PTY LTD"
    assert first.location == "Adelaide SA"
    assert first.work_type == "full_time"
    assert first.salary_label == "$87,500 - $107,500 a year"
    assert first.url.startswith("https://au.jora.com/job/Developer-Programmer-SA-")
    assert "?" not in first.url
    assert first.listed_at == NOW - timedelta(days=2)
    assert jobs[3].work_type == "contract"
    assert jobs[2].work_type == "unknown"


def test_parse_posted():
    assert parse_posted("Posted 5h ago", NOW) == NOW - timedelta(hours=5)
    assert parse_posted("Posted 3d ago", NOW) == NOW - timedelta(days=3)
    assert parse_posted("Posted just now", NOW) == NOW
    assert parse_posted("", NOW) is None


def test_parse_detail_html(fixtures_dir):
    desc, work_type = parse_detail_html((fixtures_dir / "jora_detail.html").read_text())
    assert "Phillip Riley" in desc
    assert work_type == "full_time"


class FakeResp:
    def __init__(self, text):
        self.text, self.status_code = text, 200


class FakeClient:
    def __init__(self, text):
        self.text, self.calls = text, []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return FakeResp(self.text)


def test_search_strips_all_prefix_and_filters_work_types(fixtures_dir):
    client = FakeClient((fixtures_dir / "jora_search.html").read_text())
    jobs = JoraSource(client).search(
        SearchProfile(name="t", keywords="developer", location="All Adelaide SA", work_types=["contract"]),
        max_pages=1)
    assert client.calls[0][1]["params"]["l"] == "Adelaide SA"
    assert client.calls[0][1]["params"]["a"] == "7d"
    assert {j.work_type for j in jobs} <= {"contract", "unknown"}

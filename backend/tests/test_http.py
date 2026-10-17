import pytest

from seekhunter.http import PoliteClient, SourceBlocked


class FakeResp:
    def __init__(self, status):
        self.status_code = status


class FakeSession:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = 0

    def request(self, method, url, **kw):
        self.calls += 1
        return FakeResp(self.statuses.pop(0))


def test_delays_between_requests_and_returns_response():
    sleeps = []
    c = PoliteClient(session=FakeSession([200, 200]), sleep=sleeps.append, min_delay=2, max_delay=2)
    assert c.get("http://x").status_code == 200
    assert c.get("http://x").status_code == 200
    assert sleeps == [2]


def test_backoff_then_success():
    sleeps = []
    s = FakeSession([403, 200])
    c = PoliteClient(session=s, sleep=sleeps.append, backoffs=(30, 90), min_delay=0, max_delay=0)
    assert c.get("http://x").status_code == 200
    assert sleeps == [30]


def test_blocked_after_backoffs():
    s = FakeSession([429, 429, 429])
    c = PoliteClient(session=s, sleep=lambda _: None, backoffs=(1, 2))
    with pytest.raises(SourceBlocked):
        c.get("http://x")
    assert s.calls == 3
    assert c.blocked_count == 3

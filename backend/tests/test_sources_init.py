from seekhunter.sources import build_sources


def test_build_sources_registers_linkedin_after_seek_and_jora():
    sources = build_sources()
    assert list(sources.keys()) == ["seek", "jora", "linkedin"]


def test_linkedin_source_has_a_dedicated_slower_client_with_extended_blocked_statuses():
    linkedin = build_sources()["linkedin"]
    client = linkedin.client
    assert client.min_delay == 4.0
    assert client.max_delay == 8.0
    assert 999 in client.blocked_statuses
    assert 403 in client.blocked_statuses
    assert 429 in client.blocked_statuses


def test_seek_and_jora_clients_are_unaffected_by_linkedins_blocked_statuses():
    sources = build_sources()
    assert sources["seek"].client.blocked_statuses == (403, 429, 503)
    assert sources["jora"].client.blocked_statuses == (403, 429, 503)

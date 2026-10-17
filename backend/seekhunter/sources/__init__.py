from typing import Protocol

from seekhunter.domain import JobData
from seekhunter.http import PoliteClient
from seekhunter.models import SearchProfile


class Source(Protocol):
    name: str
    client: PoliteClient

    def search(self, profile: SearchProfile, max_pages: int) -> list[JobData]: ...

    def details(self, job: JobData) -> JobData: ...


def build_sources() -> dict[str, Source]:
    from seekhunter.sources.jora import JoraSource
    from seekhunter.sources.linkedin import LinkedInSource
    from seekhunter.sources.seek import SeekSource

    # Order matters: `pipeline._collect` processes sources in this order within a run, and relies
    # on it for dedupe direction (SEEK stays canonical over jora/linkedin; between jora and
    # linkedin, whichever is processed first for a given run "wins" the canonical slot for a newly
    # seen duplicate). LinkedIn is also noticeably more aggressive about rate-limiting guests, so
    # it gets its own slower, dedicated PoliteClient.
    return {
        "seek": SeekSource(PoliteClient()),
        "jora": JoraSource(PoliteClient()),
        "linkedin": LinkedInSource(
            PoliteClient(min_delay=4.0, max_delay=8.0, blocked_statuses=(403, 429, 999))),
    }

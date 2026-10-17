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
    from seekhunter.sources.seek import SeekSource

    return {"seek": SeekSource(PoliteClient()), "jora": JoraSource(PoliteClient())}

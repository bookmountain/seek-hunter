from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from seekhunter.profile import Profile


class LLMUnavailable(Exception):
    """Provider can't serve this request (credit exhausted, auth, rate limit, timeout, bad output)."""


@dataclass
class LLMJobInput:
    key: str
    title: str
    company: str
    work_type: str
    text: str


@dataclass
class LLMScore:
    fit: int
    why: str
    contact_name: str | None = None


class JobFit(BaseModel):
    key: str
    fit: int
    why: str
    contact_name: str | None = None


class BatchFit(BaseModel):
    results: list[JobFit]


class LLMProvider(Protocol):
    name: str

    def score_batch(self, profile: Profile, jobs: list[LLMJobInput]) -> dict[str, LLMScore]: ...

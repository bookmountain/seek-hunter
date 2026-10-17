"""Pydantic shapes for the tailoring LLM's JSON reply (lenient: unknown keys ignored, all optional)."""

from pydantic import BaseModel, ConfigDict


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class SkillEdit(_Lenient):
    id: str
    items: list[str] = []


class BulletEdit(_Lenient):
    id: str
    text: str = ""


class ExperienceEdit(_Lenient):
    id: str
    bullets: list[BulletEdit] = []


class CoverLetter(_Lenient):
    greeting: str = ""
    paragraphs: list[str] = []
    sign_off: str = "Kind regards,"

    def text(self) -> str:
        return "\n\n".join([self.greeting, *self.paragraphs, f"{self.sign_off}\nBook Sam"])

    def word_count(self) -> int:
        return sum(len(p.split()) for p in self.paragraphs)


class TailorOutput(_Lenient):
    headline: str | None = None
    summary: str = ""
    skills: list[SkillEdit] = []
    experiences: list[ExperienceEdit] = []
    projects: list[str] | None = None
    keywords_matched: list[str] = []
    gaps: list[str] = []
    cover_letter: CoverLetter = CoverLetter()

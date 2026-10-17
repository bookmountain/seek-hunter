import re

from pydantic import BaseModel, Field, field_validator


class Weights(BaseModel):
    flexible_work: int = 35
    full_time: int = 10
    skill_max: int = 50
    role_max: int = 15
    skill_saturation: int = 8


class AppSettings(BaseModel):
    defence_employers: list[str] = Field(default_factory=lambda: [
        "BAE Systems", "Saab", "Raytheon", "Boeing Defence", "ASC Pty", "ASC Shipbuilding",
        "Naval Group", "Thales", "Leidos", "Babcock", "Northrop Grumman", "Kongsberg", "DSTG",
        "Defence Science and Technology", "Department of Defence", "Nova Systems", "Lockheed", "L3Harris",
        "General Dynamics", "Hanwha Defence", "Rheinmetall", "Australian Submarine Agency",
        "CEA Technologies", "Ultra Maritime", "Penten", "Silentium Defence", "Shoal Group",
        "Airbus Defence", "RTX", "Defence", "Defense",
    ])
    bank_employers: list[str] = Field(default_factory=lambda: [
        "Commonwealth Bank", "CBA", "NAB", "National Australia Bank", "ANZ", "Westpac", "BankSA", "St.George",
        "St George Bank", "Bank of Melbourne", "Macquarie Group", "Macquarie Bank", "Bendigo Bank",
        "Bendigo and Adelaide Bank", "Adelaide Bank", "BOQ", "Bank of Queensland", "ING",
        "Suncorp Bank", "HSBC", "Citi", "Bankwest", "People's Choice", "Beyond Bank",
    ])
    employer_allowlist: list[str] = Field(default_factory=list)
    clearance_patterns: list[str] = Field(default_factory=lambda: [
        r"\bNV\s*-?\s*[12]\b", r"\bNV1\b", r"\bTS\s*-?\s*PV\b", r"top\s+secret",
        r"negative vetting",
        r"\bbaseline\s+(security\s+)?clearance",
        r"\bAGSVA\b", r"\bPV\s+clearance", r"\bsecurity\s+clearance",
        r"\b(obtain|hold|maintain)\w*\s+(an?\s+)?(australian\s+)?"
        r"(government\s+)?(security\s+)?clearance",
    ])
    citizenship_patterns: list[str] = Field(default_factory=lambda: [
        r"australian\s+citizen(s|ship)?\s+(is\s+|are\s+)?(required|only|essential|mandatory|a\s+requirement)",
        r"must\s+(be|hold|have)\s+(an?\s+)?australian\s+citizen(s|ship)?",
        r"permanent\s+residen(t|ts|cy)\s+(is\s+)?(required|only)",
        r"\bPR\s+(is\s+)?required", r"citizens\s+(or|and)\s+permanent\s+residents\s+only",
        r"australian\s+citizens\s+only",
        r"(open|available)\s+to\s+australian\s+citizens",
        r"must\s+(have|hold)\s+(australian\s+)?PR\b",
        r"only\s+australian\s+citizens",
        r"\b(australian\s+)?(citizen(ship)?|PR|permanent\s+residen\w*)\s+(or|/)\s+"
        r"(citizen(ship)?|PR|permanent\s+residen\w*)\b",
        r"without\s+australian\s+citizenship",
    ])
    defence_keywords: list[str] = Field(default_factory=lambda: [
        r"defence\s+industry", r"defence\s+prime", r"defence\s+program", r"department\s+of\s+defence",
        r"defence\s+sector", r"defence\s+projects?", r"defense\s+(industry|contractor|sector)",
    ])
    bank_keywords: list[str] = Field(default_factory=lambda: [
        r"leading\s+bank", r"big\s+(four|4)\s+bank", r"major\s+bank", r"tier\s*1\s+bank",
        r"banking\s+client",
    ])
    exclude_fintech: bool = False
    fintech_keywords: list[str] = Field(default_factory=lambda: [r"\bfintech\b"])
    role_boost_terms: list[str] = Field(default_factory=lambda: [
        "software", "full stack", "full-stack", "fullstack", "frontend", "front end", "front-end",
        "backend", "back end", "developer", "ai engineer", "machine learning", "graduate", "web",
    ])
    role_penalty_terms: list[str] = Field(default_factory=lambda: [
        "principal", "head of", "director", "10+ years", "helpdesk", "help desk", "service desk",
        "desktop support", "network engineer", "technician",
    ])
    weights: Weights = Field(default_factory=Weights)
    llm_enabled: bool = True
    llm_providers: list[str] = Field(default_factory=lambda: ["anthropic", "openclaw"])
    notify_enabled: bool = True
    recap_enabled: bool = True
    max_pages_per_search: int = 3
    max_notify_per_run: int = 20

    @field_validator(
        "clearance_patterns",
        "citizenship_patterns",
        "defence_keywords",
        "bank_keywords",
        "fintech_keywords",
    )
    @classmethod
    def _validate_regex_patterns(cls, value: list[str]) -> list[str]:
        for pattern in value:
            if len(pattern) > 200:
                raise ValueError(f"regex pattern too long ({len(pattern)} > 200 chars): {pattern!r}")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid regex pattern {pattern!r}: {exc}") from exc
        return value

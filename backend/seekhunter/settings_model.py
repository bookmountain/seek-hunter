from pydantic import BaseModel, Field


class Weights(BaseModel):
    flexible_work: int = 35
    full_time: int = 10
    skill_max: int = 50
    role_max: int = 15
    skill_saturation: int = 8


class AppSettings(BaseModel):
    defence_employers: list[str] = Field(default_factory=lambda: [
        "BAE Systems", "Saab", "Lockheed Martin", "Raytheon", "Boeing Defence", "ASC Pty", "ASC Shipbuilding",
        "Naval Group", "Thales", "Leidos", "Babcock", "Northrop Grumman", "Kongsberg", "DSTG",
        "Defence Science and Technology", "Department of Defence", "Nova Systems", "Lockheed", "L3Harris",
        "General Dynamics", "Hanwha Defence", "Rheinmetall", "Australian Submarine Agency",
    ])
    bank_employers: list[str] = Field(default_factory=lambda: [
        "Commonwealth Bank", "CBA", "NAB", "National Australia Bank", "ANZ", "Westpac", "BankSA", "St.George",
        "St George Bank", "Bank of Melbourne", "Macquarie", "Bendigo", "BOQ", "Bank of Queensland", "ING",
        "Suncorp Bank", "HSBC", "Citi", "Bankwest", "People's Choice", "Beyond Bank",
    ])
    employer_allowlist: list[str] = Field(default_factory=list)
    clearance_patterns: list[str] = Field(default_factory=lambda: [
        r"\bNV1\b|\bNV 1\b", r"\bNV2\b|\bNV 2\b", r"negative vetting", r"\bbaseline\s+(security\s+)?clearance",
        r"\bAGSVA\b", r"\bPV\s+clearance", r"\bsecurity\s+clearance", r"\b(obtain|hold|maintain)\w*\s+(an?\s+)?(australian\s+)?"
        r"(government\s+)?(security\s+)?clearance",
    ])
    citizenship_patterns: list[str] = Field(default_factory=lambda: [
        r"australian\s+citizen(ship)?\s+(is\s+)?(required|only|essential|mandatory)",
        r"must\s+be\s+an?\s+australian\s+citizen", r"permanent\s+residen(t|ts|cy)\s+(is\s+)?(required|only)",
        r"\bPR\s+(is\s+)?required", r"citizens\s+(or|and)\s+permanent\s+residents\s+only",
        r"australian\s+citizens\s+only",
    ])
    defence_keywords: list[str] = Field(default_factory=lambda: [
        r"defence\s+industry", r"defence\s+prime", r"defence\s+program", r"department\s+of\s+defence",
        r"defence\s+sector", r"defence\s+projects?",
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

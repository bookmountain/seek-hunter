import re

from pydantic import BaseModel, Field, NaiveDatetime, field_validator


class Weights(BaseModel):
    """Points of the 100-point rule score (see scoring.score_job). Three components add up:
    work type (the better of `flexible_work` / `full_time`, so the work-type component is worth
    max(flexible_work, full_time)), skill match (`skill_max`, reached at `skill_saturation`
    matched skills) and role fit (`role_max`; a neutral title earns a third of it).

    Stored settings from before the "must add up to 100" rule are still loaded as-is (scoring
    caps the sum at 100); only PUT /api/settings enforces `rule_total() == 100`, and the Settings
    page offers to rebalance old values proportionally."""

    flexible_work: int = 35
    full_time: int = 10
    skill_max: int = 50
    role_max: int = 15
    skill_saturation: int = 8

    def work_max(self) -> int:
        return max(self.flexible_work, self.full_time)

    def rule_total(self) -> int:
        return self.work_max() + self.skill_max + self.role_max

    def problems(self) -> list[str]:
        """Why these weights can't be saved (empty when they're fine)."""
        points = ("flexible_work", "full_time", "skill_max", "role_max")
        out = [f"weights.{k} must not be negative" for k in points if getattr(self, k) < 0]
        if self.skill_saturation < 1:
            out.append("weights.skill_saturation must be at least 1")
        total = self.rule_total()
        if total != 100:
            out.append(
                f"score weights must add up to 100 (work type {self.work_max()} + skill match "
                f"{self.skill_max} + role fit {self.role_max} = {total})"
            )
        return out


class AppSettings(BaseModel):
    defence_employers: list[str] = Field(
        default_factory=lambda: [
            "BAE Systems",
            "Saab",
            "Raytheon",
            "Boeing Defence",
            "ASC Pty",
            "ASC Shipbuilding",
            "Naval Group",
            "Thales",
            "Leidos",
            "Babcock",
            "Northrop Grumman",
            "Kongsberg",
            "DSTG",
            "Defence Science and Technology",
            "Department of Defence",
            "Nova Systems",
            "Lockheed",
            "L3Harris",
            "General Dynamics",
            "Hanwha Defence",
            "Rheinmetall",
            "Australian Submarine Agency",
            "Australian Signals Directorate",
            "ASD",
            "ASIO",
            "Australian Security Intelligence Organisation",
            "ASIS",
            "Australian Secret Intelligence Service",
            "Office of National Intelligence",
            "ONI",
            "Defence Intelligence Organisation",
            "DIO",
            "Australian Geospatial-Intelligence Organisation",
            "AGO",
            "CEA Technologies",
            "Ultra Maritime",
            "Penten",
            "Silentium Defence",
            "Shoal Group",
            "Airbus Defence",
            "RTX",
            "Defence",
            "Defense",
        ]
    )
    # Banks are only tagged by default: most don't state a visa rule in the ad, and ad wording such as
    # "citizens only" or "PR required" is already excluded via citizenship_patterns.
    exclude_banks: bool = False
    # Always excluded: Westpac Group states it "cannot directly hire" student visa holders.
    bank_excluded_employers: list[str] = Field(
        default_factory=lambda: [
            "Westpac",
            "BankSA",
            "St.George",
            "St George Bank",
            "Bank of Melbourne",
            "BT Financial",
        ]
    )
    bank_employers: list[str] = Field(
        default_factory=lambda: [
            "Commonwealth Bank",
            "CBA",
            "NAB",
            "National Australia Bank",
            "ANZ",
            "Westpac",
            "BankSA",
            "St.George",
            "St George Bank",
            "Bank of Melbourne",
            "Macquarie Group",
            "Macquarie Bank",
            "Bendigo Bank",
            "Bendigo and Adelaide Bank",
            "Adelaide Bank",
            "BOQ",
            "Bank of Queensland",
            "ING",
            "Suncorp Bank",
            "HSBC",
            "Citi",
            "Bankwest",
            "People's Choice",
            "Beyond Bank",
            "People First Bank",
            "Heritage Bank",
            "Bank",
        ]
    )
    employer_allowlist: list[str] = Field(default_factory=list)
    clearance_patterns: list[str] = Field(
        default_factory=lambda: [
            r"\bNV\s*-?\s*[12]\b",
            r"\bNV1\b",
            r"\bTS\s*-?\s*PV\b",
            r"top\s+secret",
            r"negative vetting",
            r"\bbaseline\s+(security\s+)?clearance",
            r"\bAGSVA\b",
            r"\bPV\s+clearance",
            r"\bsecurity\s+clearance",
            r"\b(obtain|hold|maintain)\w*\s+(an?\s+)?(australian\s+)?"
            r"(government\s+)?(security\s+)?clearance",
        ]
    )
    citizenship_patterns: list[str] = Field(
        default_factory=lambda: [
            r"australian\s+citizen(s|ship)?\s+(is\s+|are\s+)?(required|only|essential|mandatory|a\s+requirement)",
            r"must\s+(be|hold|have)\s+(an?\s+)?australian\s+citizen(s|ship)?",
            r"permanent\s+residen(t|ts|cy)\s+(is\s+)?(required|only)",
            r"\bPR\s+(is\s+)?required",
            r"citizens\s+(or|and)\s+permanent\s+residents\s+only",
            r"australian\s+citizens\s+only",
            r"(open|available)\s+to\s+australian\s+citizens",
            r"must\s+(have|hold)\s+(australian\s+)?PR\b",
            r"only\s+australian\s+citizens",
            r"\b(australian\s+)?(citizen(ship)?|PR|permanent\s+residen\w*)\s+(or|/)\s+"
            r"(citizen(ship)?|PR|permanent\s+residen\w*)\b",
            r"without\s+australian\s+citizenship",
        ]
    )
    defence_keywords: list[str] = Field(
        default_factory=lambda: [
            r"defence\s+industry",
            r"defence\s+prime",
            r"defence\s+program",
            r"department\s+of\s+defence",
            r"defence\s+sector",
            r"defence\s+projects?",
            r"defense\s+(industry|contractor|sector)",
        ]
    )
    bank_keywords: list[str] = Field(
        default_factory=lambda: [
            r"leading\s+bank",
            r"big\s+(four|4)\s+bank",
            r"major\s+bank",
            r"tier\s*1\s+bank",
            r"banking\s+client",
        ]
    )
    exclude_fintech: bool = False
    # Drop jobs that aren't IT/software at all (loose Jora/LinkedIn keyword matching returns e.g.
    # therapists, civil engineers, accountants). Off-topic = title matches none of
    # it_title_patterns AND the ad mentions fewer than off_topic_min_skills tech skills.
    details_retry_per_run: int = 15
    # Ads re-checked per crawl for "no longer available"/expired (polite: one request each).
    closed_checks_per_run: int = 30
    exclude_off_topic: bool = True
    off_topic_min_skills: int = 3
    it_title_patterns: list[str] = Field(
        default_factory=lambda: [
            r"\bsoftware\b",
            r"^(?!.*\b(property|land|business|sales|residential|project)\b).*\bdevelopers?\b",
            r"^(?!.*\b(cnc|machinist|toolmaker|cam|plc)\b).*\bprogrammer",
            r"\bdevs?\b",
            r"\b(it|ict)\b",
            r"\bdata\b",
            r"\bcloud\b",
            r"\bdevops\b",
            r"\bsre\b",
            r"\bplatform\b",
            r"\b(full[ -]?stack|front[ -]?end|back[ -]?end|web)\b",
            r"\b(qa|test(er|ing)?|quality assurance)\b",
            r"\bcyber",
            r"\bsecurity analyst",
            r"\b(ai|ml|machine learning|llm)\b",
            r"\bsystems?\b",
            r"\b(service|help) ?desk\b",
            r"\bdesktop support",
            r"\btechnical support",
            r"\bsupport (analyst|engineer|officer|technician)",
            r"\bnetwork",
            r"\b(sys)?admin(istrator)?\b.*\b(system|it|network|database)",
            r"\bdatabase",
            r"\bsolutions? (architect|engineer)",
            r"\bapplication",
            r"\bintegration",
            r"\bautomation",
            r"\bdigital\b",
            r"\btechnolog",
            r"\bcomputer",
            r"\binformation (systems|technology|management)",
            r"\bproduct (owner|manager)\b",
            r"\bscrum master",
            r"\bux\b|\bui\b",
            r"\bmobile\b|\bios\b|\bandroid\b",
            r"\b(\.net|java|python|react|node|php|ruby|golang|rust|c#|c\+\+|javascript|typescript|sql|azure|aws)\b",
        ]
    )
    fintech_keywords: list[str] = Field(default_factory=lambda: [r"\bfintech\b"])
    role_boost_terms: list[str] = Field(
        default_factory=lambda: [
            "software",
            "full stack",
            "full-stack",
            "fullstack",
            "frontend",
            "front end",
            "front-end",
            "backend",
            "back end",
            "developer",
            "ai engineer",
            "machine learning",
            "graduate",
            "web",
            "it support",
            "support analyst",
            "support officer",
            "support engineer",
            "helpdesk",
            "help desk",
            "service desk",
            "desktop support",
            "technician",
        ]
    )
    role_penalty_terms: list[str] = Field(
        default_factory=lambda: [
            "principal",
            "head of",
            "director",
            "10+ years",
            "network engineer",
        ]
    )
    weights: Weights = Field(default_factory=Weights)
    # Final score = rule_blend x rule score + (1 - rule_blend) x AI score, when the AI scored the job
    # (otherwise the rule score alone). 0.6 was the hard-coded mix before this became a setting.
    rule_blend: float = Field(default=0.6, ge=0.0, le=1.0)
    llm_enabled: bool = True
    llm_providers: list[str] = Field(default_factory=lambda: ["anthropic", "openclaw"])
    notify_enabled: bool = True
    recap_enabled: bool = True
    # Follow-up loop: an application in `applied`, a LinkedIn invite, or an unanswered LinkedIn
    # message becomes due after this many days without activity; the digest is a daily Telegram
    # message (skipped when nothing is due).
    follow_up_days: int = Field(default=5, ge=1, le=60)
    follow_up_digest_enabled: bool = True
    max_pages_per_search: int = 3
    max_notify_per_run: int = 20
    max_insights_per_run: int = 250
    notify_cities: list[str] = Field(default_factory=lambda: ["adelaide"])
    other_city_max_pages: int = 2
    linkedin_enabled: bool = True
    # LinkedIn's guest search is far more rate-limit-sensitive than SEEK/Jora, so it gets its own,
    # tighter page cap (also subject to `other_city_max_pages` for non-notify cities, like every
    # other source — see pipeline._max_pages_for).
    linkedin_max_pages: int = 2
    # Listed LinkedIn jobs whose applicant count is re-read per run (one detail page each, at the
    # normal 2-5 s pacing). ~100 x 8 runs/day re-checks every listed LinkedIn job daily.
    linkedin_insights_per_run: int = 100
    # Server-side "last read" marker for the in-app notification bell (GET/POST /api/notifications).
    # Deliberately excluded from PUT /api/settings overwrites — see api.put_settings.
    notifications_read_at: NaiveDatetime | None = None
    # Per-page UI filter memory (synced across devices); owned by /api/ui-prefs, preserved on PUT.
    ui_prefs: dict = Field(default_factory=dict)
    market_enabled: bool = True
    market_cities: list[str] = Field(default_factory=lambda: ["adelaide", "melbourne", "sydney", "perth"])
    market_keywords: list[str] = Field(
        default_factory=lambda: [
            "software engineer",
            "developer",
            "full stack",
            "frontend",
            "backend",
            "AI engineer",
            "data engineer",
            "devops",
            "IT support",
        ]
    )
    market_details_per_city: int = 40
    # Indeed AU (via JobSpy) as a fourth crawl source.
    indeed_enabled: bool = True
    # Company Radar: polls employers' own ATS job feeds (Greenhouse, Lever, Ashby, Workable,
    # SmartRecruiters, Workday) every 30 min, so their ads are seen before the boards repost them.
    radar_enabled: bool = True
    # Auto-seed looks at direct employers in jobs first seen within this many days, and probes at
    # most `radar_seed_max_probe` new companies per seed run (each probe is ~3 small requests).
    radar_seed_days: int = 60
    radar_seed_max_probe: int = 80
    # Company names containing any of these (case-insensitive) are recruitment agencies, not
    # direct employers: never added to the radar.
    agency_keywords: list[str] = Field(
        default_factory=lambda: [
            "recruit", "talent", "staffing", "consulting", "personnel", "people", "search",
            "hays", "robert walters", "peoplebank", "akkodis", "hudson", "randstad", "adecco",
            "michael page", "page personnel", "chandler macleod", "finite", "paxus", "u&u",
            "talentweb", "halcyon knights", "clicks it", "davidson", "hender", "precision sourcing",
            "aurec", "drake", "programmed", "manpower", "kelly services", "slade group",
            "people2people", "charterhouse", "six degrees", "greythorn", "experis", "modis",
            "talent international", "ignite", "resourcing", "placements", "labour hire",
        ]
    )
    # Instant Telegram alert (one message per job, sent as soon as a crawl/radar run evaluates
    # it) for new notify-city jobs scoring at least this, with at most this many applicants
    # (unknown counts pass), listed within the last 24 h. Alerted jobs are left out of the digest.
    instant_alert_min_score: int = 70
    instant_alert_max_applicants: int = 20

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

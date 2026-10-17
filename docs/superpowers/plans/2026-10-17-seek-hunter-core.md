# SeekHunter Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crawl SEEK + Jora several times a day, exclude jobs Book can't take (clearance, citizenship/PR, defence, banks), score the rest against Book's resume (visa-friendly work types first), notify via OpenClaw's Telegram bot, and provide a React web UI. Deploy to `192.168.4.50`, published at `seekhunter.bookmountain.work`.

**Architecture:** Python 3.12 FastAPI backend with SQLite (SQLModel). Each job board is a `Source` module behind one protocol. Filtering and scoring are pure functions. The optional LLM scoring goes through a provider chain (Anthropic Haiku → OpenClaw/Codex → none). A `pipeline` module orchestrates runs; systemd timers invoke the CLI. A React + Vite SPA is built to static files and served by FastAPI.

**Tech Stack:** uv, Python 3.12, FastAPI, SQLModel, pydantic-settings, curl_cffi, selectolax (lexbor), anthropic SDK, pytest, ruff · React 19, Vite, TypeScript, Tailwind v4, shadcn/ui, React Router, TanStack Query, DOMPurify, Vitest · systemd, GitHub Actions (self-hosted runner on vm100), cloudflared.

**Spec:** `docs/superpowers/specs/2026-10-17-seek-hunter-core-design.md`

**Verified facts this plan relies on (2026-10-17):**
- SEEK search: `GET https://www.seek.com.au/api/jobsearch/v5/search` → JSON `{data:[...], totalCount}`; items have `id, title, advertiser.description, companyName, locations[0].label, workTypes[0]` ("Part time" / "Full time" / "Contract/Temp" / "Casual/Vacation"), `salaryLabel, listingDate, teaser, bulletPoints`. Work type ids: 242 FT, 243 PT, 244 Contract/Temp, 245 Casual.
- SEEK details: `POST https://www.seek.com.au/graphql` with `jobDetails(id)` → `data.jobDetails.job.content` (HTML).
- Jora: `GET https://au.jora.com/j?q=&l=&sp=search&a=7d&p=N` requires `curl_cffi` `impersonate="chrome"`. Cards are `div.job-card` with `id="r_<hash>"`, `h2.job-title a.job-link`, `.job-company`, `.job-location`, `.badge.-default-badge .content`, `.job-abstract`, `.job-listed-date` ("Posted 2d ago"), next page `a.next-page-button`. The detail description is `#job-description-container`.
- OpenClaw: `openclaw message send --channel telegram --target <id> --message <text>`; `openclaw agent --agent main --session-id <id> --thinking low --json -m <prompt>` → reply at `result.meta.finalAssistantVisibleText` (~16 s).
- Fixtures already committed in `backend/tests/fixtures/` (`seek_search.json`, `seek_details.json`, `jora_search.html`, `jora_detail.html`).

**Deviations from spec (simplifications, update spec in Task 1):** job status/notes/`force_include`/`notified_at` live on the `jobs` table (no separate `job_status`); one evaluation row per job (overwritten), not history; `SQLModel.metadata.create_all` instead of Alembic (add Alembic when B needs column migrations); Haiku model id is `claude-haiku-4-5`; notification candidates are "active jobs with `notified_at IS NULL` first seen in the last 48 h", capped at the top 20 per run (others are marked notified and summarized as "+N more").

---

## File Structure

```
backend/
  pyproject.toml, .python-version, uv.lock
  seekhunter/
    __init__.py
    config.py         Env (pydantic-settings)
    domain.py         JobData dataclass, normalize_work_type, html_to_text, dedupe_key
    settings_model.py AppSettings (pydantic) with default blocklists/patterns/weights
    skills.py         skill vocabulary + extract_skills()
    profile.py        Profile + load_profile(resume_dir) from book-cv LaTeX
    filters.py        evaluate_exclusions()
    scoring.py        score_job(), blend()
    http.py           PoliteClient, SourceBlocked
    sources/__init__.py  Source protocol + build_sources()
    sources/seek.py
    sources/jora.py
    llm/__init__.py
    llm/base.py       LLMUnavailable, LLMJobInput, LLMScore, LLMProvider, BatchFit models
    llm/prompt.py     build_prompt(), parse_batch_text()
    llm/anthropic_provider.py
    llm/openclaw_provider.py
    llm/chain.py      LLMChain, build_chain()
    models.py         SQLModel tables
    db.py             engine, init_db, get_session
    repo.py           DB helpers (upsert, settings, seed, queries)
    notify.py         DigestItem, format_digest(), format_recap(), Notifier
    lock.py           run_lock() file lock
    pipeline.py       run_crawl(), run_recap()
    security.py       IP allowlist middleware, require_write
    api.py            create_app()
    cli.py            `seekhunter` entrypoint
  tests/ (one test file per module + fixtures/)
frontend/
  package.json, vite.config.ts, tsconfig*.json, index.html, components.json
  src/main.tsx, App.tsx, index.css
  src/lib/api.ts, types.ts, utils.ts
  src/components/ (ui/* from shadcn, JobTable.tsx, JobDrawer.tsx, ScoreBadge.tsx, TokenDialog.tsx, Layout.tsx)
  src/pages/ JobsPage.tsx, SearchesPage.tsx, SettingsPage.tsx, RunsPage.tsx
deploy/
  systemd/seekhunter-web.service, seekhunter-crawl.service, seekhunter-crawl.timer, seekhunter-recap.service, seekhunter-recap.timer
  bootstrap-vps.sh, deploy.sh, env.example
.github/workflows/ci-deploy.yml
```

---

### Task 1: Backend scaffold + spec sync

**Files:**
- Create: `backend/pyproject.toml`, `backend/.python-version`, `backend/seekhunter/__init__.py`, `backend/seekhunter/config.py`, `backend/tests/__init__.py`, `backend/tests/conftest.py`, `backend/tests/test_config.py`, `.gitignore`
- Modify: `docs/superpowers/specs/2026-10-17-seek-hunter-core-design.md`

- [ ] **Step 1: Install uv locally if missing**

Run: `which uv || brew install uv`
Expected: a path to `uv`.

- [ ] **Step 2: Create `backend/pyproject.toml`**

```toml
[project]
name = "seekhunter"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "sqlmodel>=0.0.22",
  "pydantic-settings>=2.6",
  "curl_cffi>=0.7",
  "selectolax>=0.3.27",
  "anthropic>=0.70",
]

[project.scripts]
seekhunter = "seekhunter.cli:main"

[dependency-groups]
dev = ["pytest>=8", "ruff>=0.7", "httpx>=0.27"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["seekhunter"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 110
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
```

- [ ] **Step 3: Create `backend/.python-version`**

```
3.12
```

- [ ] **Step 4: Create `.gitignore` at repo root**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
backend/data/
.env
node_modules/
frontend/dist/
.DS_Store
```

- [ ] **Step 5: Write failing test `backend/tests/test_config.py`**

```python
from seekhunter.config import Env


def test_env_defaults_and_list_parsing(monkeypatch):
    monkeypatch.setenv("ALLOWED_PUBLIC_IPS", "1.2.3.4, 5.6.7.8")
    env = Env()
    assert env.telegram_target == "1635495359"
    assert env.allowed_public_ip_list == ["1.2.3.4", "5.6.7.8"]
    assert "192.168.4.0/24" in env.allowed_cidr_list
```

- [ ] **Step 6: Create `backend/seekhunter/__init__.py` (empty) and `backend/tests/__init__.py` (empty), then run test to verify it fails**

Run: `cd backend && uv sync && uv run pytest tests/test_config.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'seekhunter.config'`

- [ ] **Step 7: Implement `backend/seekhunter/config.py`**

```python
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/seekhunter.db"
    resume_dir: Path = Path("../../book-cv/latex/sections/resume")
    static_dir: Path = Path("../frontend/dist")
    data_dir: Path = Path("./data")
    anthropic_api_key: str | None = None
    api_write_token: str = "dev-token"
    allowed_cidrs: str = "127.0.0.1/32,192.168.4.0/24,100.64.0.0/10"
    allowed_public_ips: str = ""
    telegram_target: str = "1635495359"
    openclaw_bin: str = "openclaw"
    public_url: str = "http://localhost:8090"

    @property
    def allowed_cidr_list(self) -> list[str]:
        return [c.strip() for c in self.allowed_cidrs.split(",") if c.strip()]

    @property
    def allowed_public_ip_list(self) -> list[str]:
        return [c.strip() for c in self.allowed_public_ips.split(",") if c.strip()]


@lru_cache
def get_env() -> Env:
    return Env()
```

- [ ] **Step 8: Create `backend/tests/conftest.py`**

```python
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
```

- [ ] **Step 9: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 10: Sync spec with the deviations**

In `docs/superpowers/specs/2026-10-17-seek-hunter-core-design.md`:
- §3 Stack: replace "SQLModel + SQLite, Alembic," with "SQLModel + SQLite (tables created with `create_all`; Alembic deferred until a column migration is needed),"
- §4 tree: change `anthropic.py   Claude Haiku 4.5 (claude-haiku-4-5-20251001)` to `anthropic_provider.py   Claude Haiku 4.5 (claude-haiku-4-5)` and `openclaw.py` to `openclaw_provider.py`
- §6: replace the `job_status` bullet with "`jobs` also carries status (`new`|`saved`|`applied`|`hidden`), notes, force_include (manual un-exclude), notified_at." and change "Latest row per job is current." to "One row per job (overwritten on re-evaluation)."
- §7 step 7: replace with "Notification candidates = active jobs (not excluded or force_include, not duplicates, not hidden) with `notified_at IS NULL` first seen within 48 h. Send the top 20 by score; mark all candidates notified; append '+N more' if truncated. On send failure, write to `outbox`."
- §10: remove "`alembic upgrade head`," from the deploy steps.

- [ ] **Step 11: Commit**

```bash
git add .gitignore backend docs
git commit -m "chore: scaffold backend package and sync spec"
```

---

### Task 2: Domain types and helpers

**Files:**
- Create: `backend/seekhunter/domain.py`
- Test: `backend/tests/test_domain.py`

- [ ] **Step 1: Write failing tests**

```python
from seekhunter.domain import JobData, dedupe_key, html_to_text, normalize_work_type


def test_normalize_work_type():
    assert normalize_work_type("Part time") == "part_time"
    assert normalize_work_type("Contract/Temp") == "contract"
    assert normalize_work_type("Casual/Vacation") == "casual"
    assert normalize_work_type("Full time, Permanent") == "full_time"
    assert normalize_work_type("Temporary") == "contract"
    assert normalize_work_type("") == "unknown"
    assert normalize_work_type(None) == "unknown"


def test_html_to_text_collapses_whitespace():
    assert html_to_text("<p>Hello</p>\n<ul><li>React</li><li>C#</li></ul>") == "Hello React C#"
    assert html_to_text("") == ""


def test_dedupe_key_normalizes_company_suffixes():
    a = dedupe_key("Full Stack Developer", "Acme Pty Ltd")
    b = dedupe_key("Full-Stack  Developer", "ACME")
    assert a == b


def test_jobdata_text_prefers_description():
    job = JobData(source="seek", external_id="1", title="Dev", company="A", location="Adelaide SA",
                  work_type="part_time", url="u", teaser="short", description_html="<p>Long text</p>")
    assert job.text == "Long text"
    job2 = JobData(source="seek", external_id="2", title="Dev", company="A", location="",
                   work_type="unknown", url="u", teaser="short")
    assert job2.text == "short"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_domain.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `backend/seekhunter/domain.py`**

```python
import re
from dataclasses import dataclass
from datetime import datetime

from selectolax.lexbor import LexborHTMLParser

WORK_TYPES = ("full_time", "part_time", "contract", "casual", "unknown")
FLEXIBLE_WORK_TYPES = {"part_time", "contract", "casual"}

_COMPANY_SUFFIXES = re.compile(r"\b(pty|ltd|limited|inc|group|australia|au)\b")


def normalize_work_type(label: str | None) -> str:
    text = (label or "").lower()
    if "casual" in text:
        return "casual"
    if "contract" in text or "temp" in text:
        return "contract"
    if "part" in text:
        return "part_time"
    if "full" in text:
        return "full_time"
    return "unknown"


def html_to_text(html: str) -> str:
    if not html:
        return ""
    text = LexborHTMLParser(html).text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def dedupe_key(title: str, company: str) -> str:
    company_clean = _COMPANY_SUFFIXES.sub(" ", company.lower())
    return f"{_norm(title)}|{_norm(company_clean)}"


@dataclass
class JobData:
    source: str
    external_id: str
    title: str
    company: str
    location: str
    work_type: str
    url: str
    salary_label: str | None = None
    listed_at: datetime | None = None
    teaser: str = ""
    description_html: str = ""

    @property
    def text(self) -> str:
        return html_to_text(self.description_html) or self.teaser
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/test_domain.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/seekhunter/domain.py backend/tests/test_domain.py
git commit -m "feat: add job domain types and normalization helpers"
```

---

### Task 3: App settings model with defaults

**Files:**
- Create: `backend/seekhunter/settings_model.py`
- Test: `backend/tests/test_settings_model.py`

- [ ] **Step 1: Write failing test**

```python
from seekhunter.settings_model import AppSettings


def test_defaults_contain_core_rules():
    s = AppSettings()
    assert "BAE Systems" in s.defence_employers
    assert "Westpac" in s.bank_employers
    assert any("NV1" in p for p in s.clearance_patterns)
    assert s.weights.flexible_work == 35
    assert s.weights.full_time == 10
    assert s.llm_providers == ["anthropic", "openclaw"]


def test_roundtrip_json():
    s = AppSettings()
    s.employer_allowlist.append("Acme")
    again = AppSettings.model_validate_json(s.model_dump_json())
    assert again.employer_allowlist == ["Acme"]
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_settings_model.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `backend/seekhunter/settings_model.py`**

```python
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
        r"\bNV ?1\b", r"\bNV ?2\b", r"negative vetting", r"\bbaseline\s+(security\s+)?clearance",
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
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/test_settings_model.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/seekhunter/settings_model.py backend/tests/test_settings_model.py
git commit -m "feat: add editable app settings with default exclusion rules"
```

---

### Task 4: Skill vocabulary and extraction

**Files:**
- Create: `backend/seekhunter/skills.py`
- Test: `backend/tests/test_skills.py`

- [ ] **Step 1: Write failing tests**

```python
from seekhunter.skills import extract_skills


def test_extracts_with_aliases_and_symbols():
    text = "We use React.js, Next.js, TypeScript, C# and .NET 8 on Postgres with Docker and k8s."
    assert extract_skills(text) >= {"React", "Next.js", "TypeScript", "C#", ".NET", "PostgreSQL",
                                    "Docker", "Kubernetes"}


def test_does_not_match_inside_words():
    assert "Java" not in extract_skills("JavaScript developer")
    assert "JavaScript" in extract_skills("JavaScript developer")
    assert "Go" not in extract_skills("Go to market")
    assert "React" not in extract_skills("reactive maintenance")


def test_case_insensitive():
    assert "Python" in extract_skills("PYTHON scripting")
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_skills.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `backend/seekhunter/skills.py`**

```python
import re

# canonical display name -> aliases (plain text, matched case-insensitively with symbol-aware boundaries)
SKILL_ALIASES: dict[str, list[str]] = {
    "TypeScript": ["typescript"],
    "JavaScript": ["javascript", "es6"],
    "Python": ["python"],
    "Java": ["java"],
    "C#": ["c#", "c sharp", "csharp"],
    ".NET": [".net", "dotnet", "asp.net", ".net core"],
    "C++": ["c++"],
    "Go": ["golang"],
    "Rust": ["rust"],
    "Kotlin": ["kotlin"],
    "Swift": ["swift"],
    "PHP": ["php"],
    "Ruby": ["ruby", "ruby on rails"],
    "React": ["react", "react.js", "reactjs"],
    "Next.js": ["next.js", "nextjs"],
    "Vue": ["vue", "vue.js", "vuejs"],
    "Angular": ["angular"],
    "Redux": ["redux"],
    "Node.js": ["node.js", "nodejs", "node"],
    "NestJS": ["nestjs", "nest.js"],
    "Spring": ["spring boot", "spring"],
    "Django": ["django"],
    "FastAPI": ["fastapi"],
    "Flask": ["flask"],
    "HTML/CSS": ["html", "css", "html5", "css3"],
    "Tailwind": ["tailwind", "tailwindcss"],
    "SQL": ["sql", "t-sql", "tsql"],
    "PostgreSQL": ["postgresql", "postgres"],
    "MySQL": ["mysql"],
    "SQL Server": ["sql server", "mssql"],
    "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis"],
    "GraphQL": ["graphql"],
    "REST APIs": ["rest api", "rest apis", "restful"],
    "Microservices": ["microservices", "microservice", "micro-services"],
    "RabbitMQ": ["rabbitmq"],
    "Kafka": ["kafka"],
    "gRPC": ["grpc"],
    "Azure": ["azure"],
    "AWS": ["aws", "amazon web services"],
    "GCP": ["gcp", "google cloud"],
    "Docker": ["docker"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Terraform": ["terraform"],
    "CI/CD": ["ci/cd", "github actions", "azure devops", "jenkins", "gitlab ci"],
    "Linux": ["linux"],
    "Git": ["git"],
    "Jest": ["jest"],
    "Playwright": ["playwright"],
    "Selenium": ["selenium"],
    "LLM": ["llm", "llms", "large language model", "large language models"],
    "RAG": ["rag", "retrieval-augmented", "retrieval augmented"],
    "AI Agents": ["ai agent", "ai agents", "agentic"],
    "Prompt Engineering": ["prompt engineering"],
    "Ollama": ["ollama"],
    "OpenAI": ["openai"],
    "LangChain": ["langchain"],
    "pgvector": ["pgvector"],
    "Machine Learning": ["machine learning"],
    "PowerShell": ["powershell"],
}


def _compile(alias: str) -> re.Pattern[str]:
    return re.compile(r"(?<![A-Za-z0-9_.#+])" + re.escape(alias) + r"(?![A-Za-z0-9_#+])", re.IGNORECASE)


_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (name, _compile(alias)) for name, aliases in SKILL_ALIASES.items() for alias in aliases
]


def extract_skills(text: str) -> set[str]:
    found: set[str] = set()
    for name, pattern in _PATTERNS:
        if name not in found and pattern.search(text):
            found.add(name)
    return found
```

Note: `(?<![A-Za-z0-9_.#+])` keeps ".net" from matching inside "asp.net"-style tokens twice and stops "Java" inside "JavaScript"; the trailing `(?![A-Za-z0-9_#+])` stops "c" + "#" ambiguity and "react" inside "reactive". The `.` is allowed after a match so "React." at sentence end still matches.

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/test_skills.py -v`
Expected: 3 passed. If `.NET` fails in "and .NET 8", note that the lookbehind sees a space before `.`, so it should pass; if not, debug with `uv run python -c "from seekhunter.skills import extract_skills; print(extract_skills('and .NET 8'))"`.

- [ ] **Step 5: Commit**

```bash
git add backend/seekhunter/skills.py backend/tests/test_skills.py
git commit -m "feat: add skill vocabulary and extraction"
```

---

### Task 5: Resume profile loader (book-cv LaTeX)

**Files:**
- Create: `backend/seekhunter/profile.py`
- Test: `backend/tests/test_profile.py`, `backend/tests/fixtures/resume/` (mini LaTeX tree)

- [ ] **Step 1: Create fixture LaTeX files**

`backend/tests/fixtures/resume/skills.tex`:
```latex
%!TEX root = ../../resume.tex
\resumeSection{Skills}

\resumeSkillLine{Languages}{TypeScript, Python, C\#, Java}
\resumeSkillLine{Cloud \& Tools}{Azure AI Studio, Linux}
% \resumeSkillLine{Hidden}{Cobol}
```

`backend/tests/fixtures/resume/summary.tex`:
```latex
%!TEX root = ../../resume.tex
\resumeSection{Professional Summary}

Full-stack Software Engineer with 5 years of experience in \textbf{React} and AI.
```

`backend/tests/fixtures/resume/projects.tex`:
```latex
\resumeSection{Projects}
% \resumeProject
%   {Hidden}
%   {Fortran}
%   {
%     \item hidden
%   }
\resumeProject
  {Microservice Demo}
  {.NET 8, Next.js 14, RabbitMQ, gRPC}
  {
    \item Built a containerized auction platform with Docker.
  }
```

`backend/tests/fixtures/resume/experience/microsoft.tex`:
```latex
\resumeExperience
  {Software Engineer, VDI Team}
  {Microsoft}
  {Taipei, Taiwan}
  {Mar. 2022 -- Apr. 2025}
  {
    \item Improved reliability with Jest and React Testing Library.
  }
```

- [ ] **Step 2: Write failing test**

```python
from seekhunter.profile import load_profile


def test_load_profile_extracts_skills_titles_summary(fixtures_dir):
    p = load_profile(fixtures_dir / "resume")
    assert {"TypeScript", "Python", "C#", "Java", "Azure", "Linux", ".NET", "Next.js", "RabbitMQ",
            "gRPC", "Docker", "Jest", "React"} <= p.skills
    assert "Fortran" not in p.summary and "Cobol" not in " ".join(p.skill_lines)
    assert p.titles == ["Software Engineer, VDI Team"]
    assert p.summary.startswith("Full-stack Software Engineer with 5 years")
    assert "\\textbf" not in p.summary


def test_missing_dir_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        load_profile(tmp_path / "nope")
```

- [ ] **Step 3: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_profile.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 4: Implement `backend/seekhunter/profile.py`**

```python
import re
from dataclasses import dataclass, field
from pathlib import Path

from seekhunter.skills import extract_skills


@dataclass
class Profile:
    skills: set[str]
    summary: str
    titles: list[str]
    skill_lines: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)

    def as_prompt_text(self) -> str:
        return (
            f"Summary: {self.summary}\n"
            f"Skills: {'; '.join(self.skill_lines)}\n"
            f"Past titles: {', '.join(self.titles)}\n"
            f"Highlights: {' | '.join(self.bullets[:12])}"
        )


def _strip_comments(tex: str) -> str:
    return "\n".join(line for line in tex.splitlines() if not line.lstrip().startswith("%"))


def _clean(tex: str) -> str:
    tex = tex.replace("\\#", "#").replace("\\&", "&").replace("\\%", "%").replace("--", "-")
    tex = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", tex)
    tex = re.sub(r"\\[a-zA-Z]+\*?\{([^{}]*)\}", r"\1", tex)
    tex = re.sub(r"\\[a-zA-Z]+\*?", " ", tex)
    tex = tex.replace("{", " ").replace("}", " ")
    return re.sub(r"\s+", " ", tex).strip()


def _brace_args(tex: str, macro: str, count: int) -> list[list[str]]:
    """Return the first `count` brace arguments for every occurrence of \\macro (handles nesting)."""
    results: list[list[str]] = []
    for m in re.finditer(r"\\" + macro + r"\b", tex):
        i, args = m.end(), []
        while len(args) < count and i < len(tex):
            while i < len(tex) and tex[i] in " \t\r\n":
                i += 1
            if i >= len(tex) or tex[i] != "{":
                break
            depth, start = 0, i
            while i < len(tex):
                if tex[i] == "{" and tex[i - 1] != "\\":
                    depth += 1
                elif tex[i] == "}" and tex[i - 1] != "\\":
                    depth -= 1
                    if depth == 0:
                        args.append(tex[start + 1 : i])
                        i += 1
                        break
                i += 1
        if len(args) == count:
            results.append(args)
    return results


def _read(path: Path) -> str:
    return _strip_comments(path.read_text(encoding="utf-8")) if path.exists() else ""


def load_profile(resume_dir: Path) -> Profile:
    if not resume_dir.is_dir():
        raise FileNotFoundError(f"resume dir not found: {resume_dir}")

    skills_tex = _read(resume_dir / "skills.tex")
    skill_lines = [f"{_clean(cat)}: {_clean(vals)}" for cat, vals in _brace_args(skills_tex, "resumeSkillLine", 2)]

    summary_tex = _read(resume_dir / "summary.tex")
    summary = _clean(re.sub(r"\\resumeSection\{[^}]*\}", "", summary_tex))

    projects_tex = _read(resume_dir / "projects.tex")
    project_args = _brace_args(projects_tex, "resumeProject", 3)
    project_stacks = [_clean(args[1]) for args in project_args]
    project_bullets = [_clean(b) for args in project_args for b in args[2].split("\\item") if _clean(b)]

    titles: list[str] = []
    exp_bullets: list[str] = []
    exp_dir = resume_dir / "experience"
    for path in sorted(exp_dir.glob("*.tex")) if exp_dir.is_dir() else []:
        for args in _brace_args(_read(path), "resumeExperience", 5):
            titles.append(_clean(args[0]))
            exp_bullets.extend(_clean(b) for b in args[4].split("\\item") if _clean(b))

    bullets = exp_bullets + project_bullets
    corpus = " ".join(skill_lines + [summary] + project_stacks + bullets)
    return Profile(skills=extract_skills(corpus), summary=summary, titles=titles,
                   skill_lines=skill_lines, bullets=bullets)
```

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && uv run pytest tests/test_profile.py -v`
Expected: 2 passed

- [ ] **Step 6: Smoke-test against the real resume**

Run: `cd backend && uv run python -c "from pathlib import Path; from seekhunter.profile import load_profile; p=load_profile(Path('../../book-cv/latex/sections/resume')); print(sorted(p.skills)); print(p.titles)"`
Expected: the skill list includes TypeScript, Python, C#, Java, React, Next.js, Vue, Node.js, NestJS, Azure, PostgreSQL, Docker (if mentioned), RAG, AI Agents; titles include "Software Engineer, VDI Team".

- [ ] **Step 7: Commit**

```bash
git add backend/seekhunter/profile.py backend/tests/test_profile.py backend/tests/fixtures/resume
git commit -m "feat: load resume profile from book-cv LaTeX sections"
```

---

### Task 6: Hard exclusion filters

**Files:**
- Create: `backend/seekhunter/filters.py`
- Test: `backend/tests/test_filters.py`

- [ ] **Step 1: Write failing table-driven tests**

```python
import pytest

from seekhunter.domain import JobData
from seekhunter.filters import evaluate_exclusions
from seekhunter.settings_model import AppSettings


def job(title="Software Developer", company="Acme", text=""):
    return JobData(source="seek", external_id="1", title=title, company=company, location="Adelaide SA",
                   work_type="part_time", url="u", description_html=f"<p>{text}</p>")


@pytest.mark.parametrize("j, reason", [
    (job(text="Applicants must hold a current NV1 clearance."), "clearance"),
    (job(text="Ability to obtain a Baseline clearance is essential."), "clearance"),
    (job(text="You must be an Australian citizen to apply."), "citizenship"),
    (job(text="Australian citizens or permanent residents only."), "citizenship"),
    (job(text="Australian citizens only. No sponsorship available."), "citizenship"),
    (job(company="BAE Systems Australia"), "defence"),
    (job(text="Join a defence prime delivering naval programs."), "defence"),
    (job(company="Westpac Group"), "bank"),
    (job(company="Talent International", text="Our client, a leading bank, seeks a React dev."), "bank"),
])
def test_excluded(j, reason):
    r = evaluate_exclusions(j, AppSettings())
    assert r.excluded
    assert reason in r.reasons
    assert r.snippets[reason]


@pytest.mark.parametrize("j", [
    job(text="No security clearance required. Work rights in Australia needed."),
    job(text="A security clearance is not required for this role."),
    job(company="ANZAC Medical Centre", text="React developer"),
    job(company="Ingenia Communities", text="TypeScript role"),
    job(text="Great React and Node role, part time."),
])
def test_not_excluded(j):
    r = evaluate_exclusions(j, AppSettings())
    assert not r.excluded, r.reasons


def test_allowlist_overrides_employer_rules_not_clearance():
    s = AppSettings(employer_allowlist=["Westpac"])
    assert not evaluate_exclusions(job(company="Westpac"), s).excluded
    assert evaluate_exclusions(job(company="Westpac", text="NV1 clearance needed"), s).excluded


def test_fintech_toggle():
    j = job(text="Fast-growing fintech startup")
    assert not evaluate_exclusions(j, AppSettings()).excluded
    assert "fintech" in evaluate_exclusions(j, AppSettings(exclude_fintech=True)).reasons
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_filters.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `backend/seekhunter/filters.py`**

```python
import re
from dataclasses import dataclass, field

from seekhunter.domain import JobData
from seekhunter.settings_model import AppSettings

_PRE_NEGATION = re.compile(r"\b(no|not|without|non)\b", re.IGNORECASE)
_POST_NEGATION = re.compile(r"^\W*(is\s+|are\s+)?not\s+(required|needed|necessary)", re.IGNORECASE)
_SENTENCE_BREAK = re.compile(r"[.!?\n]")


@dataclass
class FilterResult:
    excluded: bool
    reasons: list[str] = field(default_factory=list)
    snippets: dict[str, str] = field(default_factory=dict)


def _negated(text: str, start: int, end: int) -> bool:
    pre = text[max(0, start - 30) : start]
    breaks = list(_SENTENCE_BREAK.finditer(pre))
    if breaks:
        pre = pre[breaks[-1].end() :]
    post = text[end : end + 30]
    return bool(_PRE_NEGATION.search(pre) or _POST_NEGATION.search(post))


def _first_hit(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            if not _negated(text, m.start(), m.end()):
                return text[max(0, m.start() - 40) : m.end() + 40].strip()
    return None


def _employer_hit(names: list[str], company: str) -> str | None:
    for name in names:
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", company, re.IGNORECASE):
            return company
    return None


def evaluate_exclusions(job: JobData, settings: AppSettings) -> FilterResult:
    text = f"{job.title}\n{job.text}"
    result = FilterResult(excluded=False)

    def add(reason: str, snippet: str | None) -> None:
        if snippet:
            result.reasons.append(reason)
            result.snippets[reason] = snippet

    add("clearance", _first_hit(settings.clearance_patterns, text))
    add("citizenship", _first_hit(settings.citizenship_patterns, text))

    allowlisted = _employer_hit(settings.employer_allowlist, job.company) is not None
    if not allowlisted:
        add("defence", _employer_hit(settings.defence_employers, job.company)
            or _first_hit(settings.defence_keywords, text))
        add("bank", _employer_hit(settings.bank_employers, job.company)
            or _first_hit(settings.bank_keywords, text))
        if settings.exclude_fintech:
            add("fintech", _first_hit(settings.fintech_keywords, text))

    result.excluded = bool(result.reasons)
    return result
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/test_filters.py -v`
Expected: all passed. If "Australian citizens only. No sponsorship available." fails, check that `_negated` only looks *before* the match within the same sentence (the "No" comes after, so it must not negate).

- [ ] **Step 5: Commit**

```bash
git add backend/seekhunter/filters.py backend/tests/test_filters.py
git commit -m "feat: add clearance/citizenship/defence/bank exclusion filters"
```

---

### Task 7: Rule-based scoring

**Files:**
- Create: `backend/seekhunter/scoring.py`
- Test: `backend/tests/test_scoring.py`

- [ ] **Step 1: Write failing tests**

```python
from seekhunter.domain import JobData
from seekhunter.scoring import blend, score_job
from seekhunter.settings_model import AppSettings

PROFILE = {"React", "TypeScript", "Node.js", "C#", ".NET", "Azure", "Python", "PostgreSQL", "Docker"}


def job(title="Full Stack Developer", work_type="contract", text=""):
    return JobData(source="seek", external_id="1", title=title, company="Acme", location="Adelaide SA",
                   work_type=work_type, url="u", description_html=f"<p>{text}</p>")


def test_flexible_work_beats_full_time():
    text = "React TypeScript Node.js"
    assert score_job(job(work_type="contract", text=text), PROFILE, AppSettings()).rule_score > \
        score_job(job(work_type="full_time", text=text), PROFILE, AppSettings()).rule_score


def test_skill_points_saturate_and_report_matches():
    r = score_job(job(text="React TypeScript Node.js C# .NET Azure Python PostgreSQL Docker"), PROFILE,
                  AppSettings())
    assert r.matched_skills == sorted(PROFILE)
    assert r.rule_score == 35 + 50 + 15


def test_role_penalty():
    good = score_job(job(title="Software Developer"), PROFILE, AppSettings()).rule_score
    bad = score_job(job(title="Principal Engineer"), PROFILE, AppSettings()).rule_score
    assert good - bad == 15


def test_hours_flag():
    r = score_job(job(work_type="part_time", text="Minimum 30 hours per week"), PROFILE, AppSettings())
    assert "hours" in r.flags
    r2 = score_job(job(work_type="part_time", text="20 hours per week"), PROFILE, AppSettings())
    assert "hours" not in r2.flags
    assert "flexible" in r2.flags


def test_blend():
    assert blend(80, None) == 80
    assert blend(80, 50) == 68
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_scoring.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `backend/seekhunter/scoring.py`**

```python
import re
from dataclasses import dataclass, field

from seekhunter.domain import FLEXIBLE_WORK_TYPES, JobData
from seekhunter.settings_model import AppSettings
from seekhunter.skills import extract_skills

_HOURS = re.compile(r"(\d{2})\s*\+?\s*(?:hours|hrs)\s*(?:per|a|/|each)\s*week", re.IGNORECASE)
_FULL_TIME_HOURS = re.compile(r"full[\s-]time\s+hours", re.IGNORECASE)


@dataclass
class ScoreResult:
    rule_score: int
    matched_skills: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def score_job(job: JobData, profile_skills: set[str], settings: AppSettings) -> ScoreResult:
    w = settings.weights
    text = job.text
    flags: list[str] = []

    if job.work_type in FLEXIBLE_WORK_TYPES:
        work_pts = w.flexible_work
        flags.append("flexible")
    else:
        work_pts = w.full_time

    matched = sorted(extract_skills(f"{job.title} {text}") & profile_skills)
    skill_pts = round(min(len(matched), w.skill_saturation) / w.skill_saturation * w.skill_max)

    title = job.title.lower()
    lowered = text.lower()
    if any(t in title for t in settings.role_penalty_terms) or "10+ years" in lowered:
        role_pts = 0
    elif any(t in title for t in settings.role_boost_terms):
        role_pts = w.role_max
    else:
        role_pts = w.role_max // 3

    hours = [int(h) for h in _HOURS.findall(text)]
    if (hours and max(hours) >= 24) or (job.work_type != "full_time" and _FULL_TIME_HOURS.search(text)):
        flags.append("hours")

    return ScoreResult(rule_score=min(100, work_pts + skill_pts + role_pts), matched_skills=matched, flags=flags)


def blend(rule_score: int, llm_score: int | None) -> int:
    if llm_score is None:
        return rule_score
    return round(0.6 * rule_score + 0.4 * llm_score)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/test_scoring.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/seekhunter/scoring.py backend/tests/test_scoring.py
git commit -m "feat: add rule-based job scoring with visa-friendly weighting"
```

---

### Task 8: Polite HTTP client

**Files:**
- Create: `backend/seekhunter/http.py`
- Test: `backend/tests/test_http.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_http.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `backend/seekhunter/http.py`**

```python
import random
import time
from collections.abc import Callable
from typing import Any


class SourceBlocked(Exception):
    """Raised when a source keeps answering 403/429 after backoff."""


class PoliteClient:
    def __init__(
        self,
        session: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        min_delay: float = 2.0,
        max_delay: float = 5.0,
        backoffs: tuple[float, ...] = (30.0, 90.0),
    ) -> None:
        if session is None:
            from curl_cffi import requests as cffi_requests

            session = cffi_requests.Session(impersonate="chrome")
        self.session = session
        self.sleep = sleep
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.backoffs = backoffs
        self.request_count = 0
        self.blocked_count = 0

    def get(self, url: str, **kw: Any) -> Any:
        return self._request("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> Any:
        return self._request("POST", url, **kw)

    def _request(self, method: str, url: str, **kw: Any) -> Any:
        if self.request_count > 0:
            self.sleep(random.uniform(self.min_delay, self.max_delay))
        self.request_count += 1
        for attempt in range(len(self.backoffs) + 1):
            resp = self.session.request(method, url, timeout=30, **kw)
            if resp.status_code not in (403, 429):
                return resp
            self.blocked_count += 1
            if attempt < len(self.backoffs):
                self.sleep(self.backoffs[attempt])
        raise SourceBlocked(f"{method} {url} blocked ({resp.status_code})")
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/test_http.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/seekhunter/http.py backend/tests/test_http.py
git commit -m "feat: add polite HTTP client with browser impersonation and backoff"
```

---

### Task 9: Database models and repository basics

**Files:**
- Create: `backend/seekhunter/models.py`, `backend/seekhunter/db.py`, `backend/seekhunter/repo.py`
- Test: `backend/tests/test_repo.py`

- [ ] **Step 1: Write failing tests**

```python
from datetime import timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from seekhunter import repo
from seekhunter.domain import JobData
from seekhunter.models import utcnow


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def data(ext="1", source="seek", title="Dev", company="Acme"):
    return JobData(source=source, external_id=ext, title=title, company=company, location="Adelaide SA",
                   work_type="part_time", url=f"https://x/{ext}")


def test_upsert_marks_new_once(session):
    job, is_new = repo.upsert_job(session, data())
    assert is_new and job.id is not None
    job2, is_new2 = repo.upsert_job(session, data())
    assert not is_new2 and job2.id == job.id


def test_settings_roundtrip_and_seed(session):
    repo.ensure_seed(session)
    s = repo.load_settings(session)
    s.employer_allowlist = ["Acme"]
    repo.save_settings(session, s)
    assert repo.load_settings(session).employer_allowlist == ["Acme"]
    profiles = repo.list_search_profiles(session)
    assert any(p.keywords == "software engineer" for p in profiles)
    repo.ensure_seed(session)
    assert len(repo.list_search_profiles(session)) == len(profiles)


def test_find_duplicate_across_sources(session):
    seek_job, _ = repo.upsert_job(session, data(ext="1", source="seek", title="Full Stack Developer",
                                                company="Acme Pty Ltd"))
    jora_job, _ = repo.upsert_job(session, data(ext="abc", source="jora", title="Full-Stack Developer",
                                                company="ACME"))
    assert repo.find_duplicate(session, jora_job) == seek_job.id


def test_notification_candidates(session):
    j, _ = repo.upsert_job(session, data())
    repo.save_evaluation(session, j.id, excluded=False, reasons=[], snippets={}, rule_score=70,
                         llm_score=None, llm_note=None, llm_provider=None, final_score=70,
                         matched_skills=[], flags=[])
    old, _ = repo.upsert_job(session, data(ext="2"))
    old.first_seen_at = utcnow() - timedelta(days=3)
    session.add(old)
    session.commit()
    repo.save_evaluation(session, old.id, excluded=False, reasons=[], snippets={}, rule_score=90,
                         llm_score=None, llm_note=None, llm_provider=None, final_score=90,
                         matched_skills=[], flags=[])
    cands = repo.notification_candidates(session, utcnow())
    assert [c[0].id for c in cands] == [j.id]
    repo.mark_notified(session, [j.id], utcnow())
    assert repo.notification_candidates(session, utcnow()) == []
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_repo.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `backend/seekhunter/models.py`**

```python
from datetime import UTC, datetime

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """Naive UTC. SQLite drops tzinfo, so the whole app stores and compares naive UTC datetimes."""
    return datetime.now(UTC).replace(tzinfo=None)


class Job(SQLModel, table=True):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    external_id: str
    title: str
    company: str = ""
    location: str = ""
    work_type: str = "unknown"
    salary_label: str | None = None
    listed_at: datetime | None = None
    url: str
    teaser: str = ""
    description_html: str = ""
    dedupe_key: str = Field(index=True)
    canonical_job_id: int | None = Field(default=None, index=True)
    first_seen_at: datetime = Field(default_factory=utcnow, index=True)
    status: str = "new"
    notes: str = ""
    force_include: bool = False
    notified_at: datetime | None = None


class JobEvaluation(SQLModel, table=True):
    __tablename__ = "job_evaluations"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", unique=True, index=True)
    excluded: bool = False
    reasons: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    snippets: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    rule_score: int = 0
    llm_score: int | None = None
    llm_note: str | None = None
    llm_provider: str | None = None
    final_score: int = 0
    matched_skills: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    flags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class SearchProfile(SQLModel, table=True):
    __tablename__ = "search_profiles"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    keywords: str
    location: str = "All Adelaide SA"
    work_types: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    sources: list[str] = Field(default_factory=lambda: ["seek", "jora"], sa_column=Column(JSON))
    enabled: bool = True


class SettingsRow(SQLModel, table=True):
    __tablename__ = "settings"

    id: int = Field(default=1, primary_key=True)
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))


class Run(SQLModel, table=True):
    __tablename__ = "runs"

    id: int | None = Field(default=None, primary_key=True)
    kind: str = "crawl"  # crawl | recap | alert
    started_at: datetime = Field(default_factory=utcnow, index=True)
    finished_at: datetime | None = None
    source_status: dict = Field(default_factory=dict, sa_column=Column(JSON))
    new_jobs: int = 0
    notified: int = 0
    llm_provider: str | None = None
    error: str | None = None


class Outbox(SQLModel, table=True):
    __tablename__ = "outbox"

    id: int | None = Field(default=None, primary_key=True)
    text: str
    attempts: int = 0
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    sent_at: datetime | None = None
```

- [ ] **Step 4: Implement `backend/seekhunter/db.py`**

```python
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, event
from sqlmodel import Session, SQLModel, create_engine

from seekhunter.config import get_env


@lru_cache
def get_engine() -> Engine:
    env = get_env()
    if env.database_url.startswith("sqlite:///"):
        from pathlib import Path

        Path(env.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(env.database_url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _wal(dbapi_conn, _):  # noqa: ANN001
        dbapi_conn.execute("PRAGMA journal_mode=WAL")

    return engine


def init_db(engine: Engine | None = None) -> None:
    from seekhunter import models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(engine or get_engine())


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
```

- [ ] **Step 5: Implement `backend/seekhunter/repo.py`**

```python
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlmodel import Session, col, select

from seekhunter.domain import JobData, dedupe_key
from seekhunter.models import Job, JobEvaluation, Outbox, Run, SearchProfile, SettingsRow
from seekhunter.settings_model import AppSettings

DEFAULT_KEYWORDS = ["software engineer", "developer", "full stack", "frontend", "AI engineer", "graduate developer"]


def upsert_job(session: Session, data: JobData) -> tuple[Job, bool]:
    existing = session.exec(
        select(Job).where(Job.source == data.source, Job.external_id == data.external_id)
    ).first()
    if existing:
        return existing, False
    job = Job(
        source=data.source, external_id=data.external_id, title=data.title, company=data.company,
        location=data.location, work_type=data.work_type, salary_label=data.salary_label,
        listed_at=data.listed_at, url=data.url, teaser=data.teaser, description_html=data.description_html,
        dedupe_key=dedupe_key(data.title, data.company),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job, True


def update_job_details(session: Session, job: Job, data: JobData) -> None:
    job.description_html = data.description_html or job.description_html
    if job.work_type == "unknown" and data.work_type != "unknown":
        job.work_type = data.work_type
    session.add(job)
    session.commit()


def to_jobdata(job: Job) -> JobData:
    return JobData(source=job.source, external_id=job.external_id, title=job.title, company=job.company,
                   location=job.location, work_type=job.work_type, url=job.url, salary_label=job.salary_label,
                   listed_at=job.listed_at, teaser=job.teaser, description_html=job.description_html)


def find_duplicate(session: Session, job: Job) -> int | None:
    other = session.exec(
        select(Job).where(Job.dedupe_key == job.dedupe_key, Job.id != job.id, Job.source != job.source,
                          col(Job.canonical_job_id).is_(None))
        .order_by(col(Job.id))
    ).first()
    return other.id if other else None


def save_evaluation(session: Session, job_id: int, **fields) -> JobEvaluation:
    ev = session.exec(select(JobEvaluation).where(JobEvaluation.job_id == job_id)).first() or JobEvaluation(
        job_id=job_id)
    for k, v in fields.items():
        setattr(ev, k, v)
    session.add(ev)
    session.commit()
    session.refresh(ev)
    return ev


def _active_clause():
    return (
        col(Job.canonical_job_id).is_(None),
        Job.status != "hidden",
        or_(JobEvaluation.excluded == False, Job.force_include == True),  # noqa: E712
    )


def notification_candidates(session: Session, now: datetime) -> list[tuple[Job, JobEvaluation]]:
    stmt = (
        select(Job, JobEvaluation).join(JobEvaluation, JobEvaluation.job_id == Job.id)
        .where(*_active_clause(), col(Job.notified_at).is_(None), Job.first_seen_at >= now - timedelta(hours=48))
        .order_by(col(JobEvaluation.final_score).desc(), col(Job.first_seen_at).desc())
    )
    return list(session.exec(stmt).all())


def mark_notified(session: Session, job_ids: list[int], when: datetime) -> None:
    for job in session.exec(select(Job).where(col(Job.id).in_(job_ids))).all():
        job.notified_at = when
        session.add(job)
    session.commit()


def list_jobs(session: Session, view: str = "active", status: str | None = None, work_type: str | None = None,
              source: str | None = None, q: str | None = None, since: datetime | None = None,
              limit: int = 200, offset: int = 0) -> list[tuple[Job, JobEvaluation]]:
    stmt = select(Job, JobEvaluation).join(JobEvaluation, JobEvaluation.job_id == Job.id)
    if view == "excluded":
        stmt = stmt.where(JobEvaluation.excluded == True, Job.force_include == False)  # noqa: E712
        stmt = stmt.order_by(col(Job.first_seen_at).desc())
    else:
        stmt = stmt.where(col(Job.canonical_job_id).is_(None),
                          or_(JobEvaluation.excluded == False, Job.force_include == True))  # noqa: E712
        stmt = stmt.where(Job.status == status) if status else stmt.where(Job.status != "hidden")
        stmt = stmt.order_by(col(JobEvaluation.final_score).desc(), col(Job.first_seen_at).desc())
    if work_type:
        stmt = stmt.where(Job.work_type == work_type)
    if source:
        stmt = stmt.where(Job.source == source)
    if since:
        stmt = stmt.where(Job.first_seen_at >= since)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(col(Job.title).ilike(like), col(Job.company).ilike(like)))
    return list(session.exec(stmt.offset(offset).limit(limit)).all())


def count_excluded_since(session: Session, since: datetime) -> int:
    stmt = select(Job).join(JobEvaluation, JobEvaluation.job_id == Job.id).where(
        JobEvaluation.excluded == True, Job.first_seen_at >= since)  # noqa: E712
    return len(session.exec(stmt).all())


def load_settings(session: Session) -> AppSettings:
    row = session.get(SettingsRow, 1)
    return AppSettings.model_validate(row.data) if row and row.data else AppSettings()


def save_settings(session: Session, settings: AppSettings) -> None:
    row = session.get(SettingsRow, 1) or SettingsRow(id=1)
    row.data = settings.model_dump()
    session.add(row)
    session.commit()


def list_search_profiles(session: Session, enabled_only: bool = False) -> list[SearchProfile]:
    stmt = select(SearchProfile).order_by(col(SearchProfile.id))
    if enabled_only:
        stmt = stmt.where(SearchProfile.enabled == True)  # noqa: E712
    return list(session.exec(stmt).all())


def ensure_seed(session: Session) -> None:
    if session.get(SettingsRow, 1) is None:
        save_settings(session, AppSettings())
    if not list_search_profiles(session):
        for kw in DEFAULT_KEYWORDS:
            session.add(SearchProfile(name=f"Adelaide · {kw}", keywords=kw, location="All Adelaide SA"))
        session.commit()


def recent_runs(session: Session, kind: str = "crawl", limit: int = 50) -> list[Run]:
    return list(session.exec(
        select(Run).where(Run.kind == kind).order_by(col(Run.started_at).desc()).limit(limit)).all())


def pending_outbox(session: Session) -> list[Outbox]:
    return list(session.exec(
        select(Outbox).where(col(Outbox.sent_at).is_(None), Outbox.attempts < 10).order_by(col(Outbox.id))).all())
```

- [ ] **Step 6: Run to verify pass**

Run: `cd backend && uv run pytest tests/test_repo.py -v`
Expected: 4 passed. (All "now" values in the app come from `models.utcnow()`, which is naive UTC.)

- [ ] **Step 7: Commit**

```bash
git add backend/seekhunter/models.py backend/seekhunter/db.py backend/seekhunter/repo.py backend/tests/test_repo.py
git commit -m "feat: add SQLite models and repository helpers"
```

---

### Task 10: SEEK source

**Files:**
- Create: `backend/seekhunter/sources/__init__.py`, `backend/seekhunter/sources/seek.py`
- Test: `backend/tests/test_seek.py`

- [ ] **Step 1: Write failing tests**

```python
import json

from seekhunter.models import SearchProfile
from seekhunter.sources.seek import SeekSource, parse_search_item


class FakeResp:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, search, details):
        self.search, self.details, self.calls = search, details, []

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return FakeResp(self.search)

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return FakeResp(self.details)


def test_parse_search_item(fixtures_dir):
    item = json.loads((fixtures_dir / "seek_search.json").read_text())["data"][0]
    job = parse_search_item(item)
    assert job.source == "seek"
    assert job.external_id == "95229403"
    assert job.company == "Virginia Nursery"
    assert job.work_type == "part_time"
    assert job.location == "Virginia, Adelaide SA"
    assert job.url == "https://www.seek.com.au/job/95229403"
    assert job.listed_at is not None
    assert "Microsoft Access" in job.teaser


def test_search_builds_params_and_stops_at_total(fixtures_dir):
    payload = json.loads((fixtures_dir / "seek_search.json").read_text())
    payload["totalCount"] = 5
    client = FakeClient(payload, {})
    src = SeekSource(client)
    jobs = src.search(SearchProfile(name="t", keywords="developer", location="All Adelaide SA",
                                    work_types=["part_time", "contract"]), max_pages=3)
    assert len(jobs) == 5
    assert len(client.calls) == 1
    params = client.calls[0][2]["params"]
    assert params["where"] == "All Adelaide SA"
    assert params["worktype"] == "243,244"
    assert params["daterange"] == 7


def test_details_fills_description(fixtures_dir):
    item = json.loads((fixtures_dir / "seek_search.json").read_text())["data"][0]
    details = json.loads((fixtures_dir / "seek_details.json").read_text())
    src = SeekSource(FakeClient({}, details))
    job = src.details(parse_search_item(item))
    assert "Virginia Nursery Pty Ltd" in job.description_html
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_seek.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `backend/seekhunter/sources/__init__.py`**

```python
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
```

- [ ] **Step 4: Implement `backend/seekhunter/sources/seek.py`**

```python
from dataclasses import replace
from datetime import datetime

from seekhunter.domain import JobData, normalize_work_type
from seekhunter.models import SearchProfile

SEARCH_URL = "https://www.seek.com.au/api/jobsearch/v5/search"
GRAPHQL_URL = "https://www.seek.com.au/graphql"
PAGE_SIZE = 22
WORKTYPE_IDS = {"full_time": "242", "part_time": "243", "contract": "244", "casual": "245"}
DETAILS_QUERY = "query jobDetails($jobId: ID!) { jobDetails(id: $jobId) { job { id content(platform: WEB) } } }"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def parse_search_item(item: dict) -> JobData:
    job_id = str(item["id"])
    locations = item.get("locations") or []
    teaser = " ".join([item.get("teaser") or "", *(item.get("bulletPoints") or [])]).strip()
    return JobData(
        source="seek",
        external_id=job_id,
        title=item.get("title", ""),
        company=(item.get("advertiser") or {}).get("description") or item.get("companyName") or "",
        location=locations[0]["label"] if locations else "",
        work_type=normalize_work_type((item.get("workTypes") or [""])[0]),
        url=f"https://www.seek.com.au/job/{job_id}",
        salary_label=item.get("salaryLabel") or None,
        listed_at=_parse_dt(item.get("listingDate")),
        teaser=teaser,
    )


class SeekSource:
    name = "seek"

    def __init__(self, client) -> None:  # noqa: ANN001
        self.client = client

    def search(self, profile: SearchProfile, max_pages: int) -> list[JobData]:
        jobs: list[JobData] = []
        for page in range(1, max_pages + 1):
            params = {
                "siteKey": "AU-Main", "where": profile.location, "keywords": profile.keywords, "page": page,
                "pageSize": PAGE_SIZE, "daterange": 7, "locale": "en-AU",
            }
            ids = [WORKTYPE_IDS[w] for w in profile.work_types if w in WORKTYPE_IDS]
            if ids:
                params["worktype"] = ",".join(ids)
            payload = self.client.get(SEARCH_URL, params=params).json()
            jobs.extend(parse_search_item(item) for item in payload.get("data") or [])
            if page * PAGE_SIZE >= int(payload.get("totalCount") or 0):
                break
        return jobs

    def details(self, job: JobData) -> JobData:
        payload = self.client.post(
            GRAPHQL_URL,
            json={"operationName": "jobDetails", "variables": {"jobId": job.external_id}, "query": DETAILS_QUERY},
            headers={"seek-request-brand": "seek", "seek-request-country": "AU"},
        ).json()
        content = ((((payload.get("data") or {}).get("jobDetails") or {}).get("job")) or {}).get("content")
        return replace(job, description_html=content) if content else job
```

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && uv run pytest tests/test_seek.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add backend/seekhunter/sources backend/tests/test_seek.py
git commit -m "feat: add SEEK source (JSON search + GraphQL details)"
```

---

### Task 11: Jora source

**Files:**
- Create: `backend/seekhunter/sources/jora.py`
- Test: `backend/tests/test_jora.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_jora.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `backend/seekhunter/sources/jora.py`**

```python
import re
from dataclasses import replace
from datetime import datetime, timedelta

from selectolax.lexbor import LexborHTMLParser

from seekhunter.domain import JobData, normalize_work_type
from seekhunter.models import SearchProfile, utcnow

BASE = "https://au.jora.com"
_POSTED = re.compile(r"(\d+)\s*([mhdw])", re.IGNORECASE)
_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def parse_posted(text: str, now: datetime) -> datetime | None:
    if not text:
        return None
    m = _POSTED.search(text)
    if not m:
        return now if "just" in text.lower() or "today" in text.lower() else None
    return now - timedelta(**{_UNITS[m.group(2).lower()]: int(m.group(1))})


def _text(node) -> str:  # noqa: ANN001
    return node.text(strip=True) if node else ""


def parse_search_html(html: str, now: datetime) -> tuple[list[JobData], bool]:
    tree = LexborHTMLParser(html)
    jobs: list[JobData] = []
    for card in tree.css("div.job-card"):
        link = card.css_first("h2.job-title a.job-link")
        card_id = card.attributes.get("id") or ""
        if not link or not card_id.startswith("r_"):
            continue
        badges = [b.text(strip=True) for b in card.css(".badge.-default-badge .content")]
        salary = next((b for b in badges if "$" in b), None)
        work_type = next((normalize_work_type(b) for b in badges if normalize_work_type(b) != "unknown"),
                         "unknown")
        href = (link.attributes.get("href") or "").split("?")[0]
        jobs.append(JobData(
            source="jora", external_id=card_id[2:], title=link.text(strip=True),
            company=_text(card.css_first(".job-company")), location=_text(card.css_first(".job-location")),
            work_type=work_type, url=BASE + href, salary_label=salary,
            listed_at=parse_posted(_text(card.css_first(".job-listed-date")), now),
            teaser=card.css_first(".job-abstract").text(separator=" ", strip=True)
            if card.css_first(".job-abstract") else "",
        ))
    return jobs, tree.css_first("a.next-page-button") is not None


def parse_detail_html(html: str) -> tuple[str, str]:
    tree = LexborHTMLParser(html)
    container = tree.css_first("#job-description-container")
    badges = [b.text(strip=True) for b in tree.css(".badge .content")]
    work_type = next((normalize_work_type(b) for b in badges if normalize_work_type(b) != "unknown"), "unknown")
    return (container.html if container else ""), work_type


class JoraSource:
    name = "jora"

    def __init__(self, client) -> None:  # noqa: ANN001
        self.client = client

    def search(self, profile: SearchProfile, max_pages: int) -> list[JobData]:
        location = profile.location.removeprefix("All ").strip()
        wanted = set(profile.work_types)
        jobs: list[JobData] = []
        for page in range(1, max_pages + 1):
            params = {"q": profile.keywords, "l": location, "sp": "search", "a": "7d"}
            if page > 1:
                params["p"] = page
            page_jobs, has_next = parse_search_html(self.client.get(f"{BASE}/j", params=params).text, utcnow())
            jobs.extend(j for j in page_jobs if not wanted or j.work_type in wanted or j.work_type == "unknown")
            if not has_next:
                break
        return jobs

    def details(self, job: JobData) -> JobData:
        desc, work_type = parse_detail_html(self.client.get(job.url).text)
        return replace(job, description_html=desc or job.description_html,
                       work_type=job.work_type if job.work_type != "unknown" else work_type)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/test_jora.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/seekhunter/sources/jora.py backend/tests/test_jora.py
git commit -m "feat: add Jora source with browser-impersonated scraping"
```

---

### Task 12: LLM base, prompt, and chain

**Files:**
- Create: `backend/seekhunter/llm/__init__.py` (empty), `backend/seekhunter/llm/base.py`, `backend/seekhunter/llm/prompt.py`, `backend/seekhunter/llm/chain.py`
- Test: `backend/tests/test_llm_chain.py`

- [ ] **Step 1: Write failing tests**

```python
from seekhunter.llm.base import LLMJobInput, LLMScore, LLMUnavailable
from seekhunter.llm.chain import LLMChain
from seekhunter.llm.prompt import build_prompt, parse_batch_text
from seekhunter.profile import Profile

PROFILE = Profile(skills={"React"}, summary="Full-stack engineer", titles=["Software Engineer"],
                  skill_lines=["Languages: TypeScript"], bullets=["Built things"])
JOBS = [LLMJobInput(key="1", title="Dev", company="A", work_type="contract", text="React role")]


class Dead:
    name = "dead"

    def __init__(self):
        self.calls = 0

    def score_batch(self, profile, jobs):
        self.calls += 1
        raise LLMUnavailable("out of credit")


class Good:
    name = "good"

    def score_batch(self, profile, jobs):
        return {j.key: LLMScore(fit=77, why="fits") for j in jobs}


def test_chain_falls_through_and_remembers_dead_provider():
    dead = Dead()
    chain = LLMChain([dead, Good()])
    scores, provider = chain.score_batch(PROFILE, JOBS)
    assert provider == "good" and scores["1"].fit == 77
    chain.score_batch(PROFILE, JOBS)
    assert dead.calls == 1


def test_chain_all_unavailable_returns_empty():
    assert LLMChain([Dead()]).score_batch(PROFILE, JOBS) == ({}, None)
    assert LLMChain([]).score_batch(PROFILE, JOBS) == ({}, None)


def test_prompt_contains_profile_and_keys():
    system, user = build_prompt(PROFILE, JOBS)
    assert "student visa" in system.lower()
    assert '"key": "1"' in user and "Full-stack engineer" in user


def test_parse_batch_text_extracts_json_from_noise():
    raw = 'Sure!\n{"results": [{"key": "1", "fit": 150, "why": "great"}]}\nThanks'
    out = parse_batch_text(raw)
    assert out["1"].fit == 100 and out["1"].why == "great"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_llm_chain.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `backend/seekhunter/llm/base.py`**

```python
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


class JobFit(BaseModel):
    key: str
    fit: int
    why: str


class BatchFit(BaseModel):
    results: list[JobFit]


class LLMProvider(Protocol):
    name: str

    def score_batch(self, profile: Profile, jobs: list[LLMJobInput]) -> dict[str, LLMScore]: ...
```

- [ ] **Step 4: Implement `backend/seekhunter/llm/prompt.py`**

```python
import json

from pydantic import ValidationError

from seekhunter.llm.base import BatchFit, LLMJobInput, LLMScore, LLMUnavailable
from seekhunter.profile import Profile

SYSTEM = (
    "You rate how well job ads fit one candidate. The candidate is a full-stack software engineer in "
    "Adelaide on an Australian student visa until mid-2027, so part-time, casual, and contract roles are "
    "most practical; full-time roles are still relevant for after graduation. For each job return an "
    "integer fit from 0 to 100 (skills/experience overlap and realistic seniority) and a one-sentence "
    "'why' (max 20 words) naming the strongest overlap or the main gap. Return JSON only: "
    '{"results": [{"key": "...", "fit": 0, "why": "..."}]} with one entry per job key.'
)


def build_prompt(profile: Profile, jobs: list[LLMJobInput]) -> tuple[str, str]:
    payload = [
        {"key": j.key, "title": j.title, "company": j.company, "work_type": j.work_type, "ad": j.text[:3500]}
        for j in jobs
    ]
    user = f"CANDIDATE\n{profile.as_prompt_text()}\n\nJOBS\n{json.dumps(payload, ensure_ascii=False)}"
    return SYSTEM, user


def to_scores(batch: BatchFit) -> dict[str, LLMScore]:
    return {r.key: LLMScore(fit=max(0, min(100, r.fit)), why=r.why.strip()) for r in batch.results}


def parse_batch_text(raw: str) -> dict[str, LLMScore]:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise LLMUnavailable("no JSON object in model output")
    try:
        return to_scores(BatchFit.model_validate_json(raw[start : end + 1]))
    except ValidationError as e:
        raise LLMUnavailable(f"invalid JSON from model: {e}") from e
```

- [ ] **Step 5: Implement `backend/seekhunter/llm/chain.py`**

```python
import logging

from seekhunter.config import Env
from seekhunter.llm.base import LLMJobInput, LLMProvider, LLMScore, LLMUnavailable
from seekhunter.profile import Profile
from seekhunter.settings_model import AppSettings

log = logging.getLogger(__name__)


class LLMChain:
    def __init__(self, providers: list[LLMProvider]) -> None:
        self.providers = providers
        self._dead: set[str] = set()

    def score_batch(self, profile: Profile, jobs: list[LLMJobInput]) -> tuple[dict[str, LLMScore], str | None]:
        for provider in self.providers:
            if provider.name in self._dead:
                continue
            try:
                return provider.score_batch(profile, jobs), provider.name
            except LLMUnavailable as e:
                log.warning("LLM provider %s unavailable: %s", provider.name, e)
                self._dead.add(provider.name)
        return {}, None


def build_chain(settings: AppSettings, env: Env) -> LLMChain:
    if not settings.llm_enabled:
        return LLMChain([])
    providers: list[LLMProvider] = []
    for name in settings.llm_providers:
        if name == "anthropic" and env.anthropic_api_key:
            from seekhunter.llm.anthropic_provider import AnthropicProvider

            providers.append(AnthropicProvider(env.anthropic_api_key))
        elif name == "openclaw":
            from seekhunter.llm.openclaw_provider import OpenClawProvider

            providers.append(OpenClawProvider(env.openclaw_bin))
    return LLMChain(providers)
```

- [ ] **Step 6: Run to verify pass**

Run: `cd backend && uv run pytest tests/test_llm_chain.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add backend/seekhunter/llm backend/tests/test_llm_chain.py
git commit -m "feat: add LLM provider chain, prompt, and output parsing"
```

---

### Task 13: Anthropic and OpenClaw providers

**Files:**
- Create: `backend/seekhunter/llm/anthropic_provider.py`, `backend/seekhunter/llm/openclaw_provider.py`
- Test: `backend/tests/test_llm_providers.py`

- [ ] **Step 1: Write failing tests**

```python
import json
import subprocess
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from seekhunter.llm.anthropic_provider import AnthropicProvider
from seekhunter.llm.base import BatchFit, JobFit, LLMJobInput, LLMUnavailable
from seekhunter.llm.openclaw_provider import OpenClawProvider
from seekhunter.profile import Profile

PROFILE = Profile(skills=set(), summary="s", titles=[], skill_lines=[], bullets=[])
JOBS = [LLMJobInput(key="1", title="Dev", company="A", work_type="contract", text="React")]


class FakeMessages:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.kwargs = result, error, None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return SimpleNamespace(parsed_output=self.result)


def test_anthropic_success_uses_haiku_and_schema():
    msgs = FakeMessages(result=BatchFit(results=[JobFit(key="1", fit=80, why="React match")]))
    p = AnthropicProvider("k", client=SimpleNamespace(messages=msgs))
    out = p.score_batch(PROFILE, JOBS)
    assert out["1"].fit == 80
    assert msgs.kwargs["model"] == "claude-haiku-4-5"
    assert msgs.kwargs["output_format"] is BatchFit


def test_anthropic_api_error_becomes_unavailable():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.APIStatusError("credit balance too low", response=httpx.Response(400, request=req), body=None)
    p = AnthropicProvider("k", client=SimpleNamespace(messages=FakeMessages(error=err)))
    with pytest.raises(LLMUnavailable):
        p.score_batch(PROFILE, JOBS)


def test_openclaw_parses_envelope(monkeypatch):
    envelope = {"status": "ok", "result": {"meta": {
        "finalAssistantVisibleText": '{"results": [{"key": "1", "fit": 60, "why": "ok"}]}'}}}
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="log line\n" + json.dumps(envelope), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = OpenClawProvider("openclaw").score_batch(PROFILE, JOBS)
    assert out["1"].fit == 60
    assert captured["cmd"][:4] == ["openclaw", "agent", "--agent", "main"]
    assert "--json" in captured["cmd"]


def test_openclaw_failure_becomes_unavailable(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "boom"))
    with pytest.raises(LLMUnavailable):
        OpenClawProvider("openclaw").score_batch(PROFILE, JOBS)
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_llm_providers.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `backend/seekhunter/llm/anthropic_provider.py`**

```python
import anthropic

from seekhunter.llm.base import BatchFit, LLMJobInput, LLMScore, LLMUnavailable
from seekhunter.llm.prompt import build_prompt, to_scores
from seekhunter.profile import Profile

MODEL = "claude-haiku-4-5"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, client: anthropic.Anthropic | None = None) -> None:
        self.client = client or anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=90.0)

    def score_batch(self, profile: Profile, jobs: list[LLMJobInput]) -> dict[str, LLMScore]:
        system, user = build_prompt(profile, jobs)
        try:
            response = self.client.messages.parse(
                model=MODEL,
                max_tokens=2000,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=BatchFit,
            )
        except anthropic.APIError as e:  # 402 billing, 400 low credit, 401/403, 429 after retries, 5xx, network
            raise LLMUnavailable(f"anthropic: {e}") from e
        if response.parsed_output is None:
            raise LLMUnavailable("anthropic: no parsed output")
        return to_scores(response.parsed_output)
```

- [ ] **Step 4: Implement `backend/seekhunter/llm/openclaw_provider.py`**

```python
import json
import subprocess
from datetime import date

from seekhunter.llm.base import LLMJobInput, LLMScore, LLMUnavailable
from seekhunter.llm.prompt import build_prompt, parse_batch_text
from seekhunter.profile import Profile


class OpenClawProvider:
    """Uses OpenClaw's gateway agent (Codex via OpenAI OAuth). ~15 s per call, so callers batch jobs."""

    name = "openclaw"

    def __init__(self, bin_path: str = "openclaw", timeout: int = 300) -> None:
        self.bin_path = bin_path
        self.timeout = timeout

    def score_batch(self, profile: Profile, jobs: list[LLMJobInput]) -> dict[str, LLMScore]:
        system, user = build_prompt(profile, jobs)
        cmd = [
            self.bin_path, "agent", "--agent", "main",
            "--session-id", f"seekhunter-{date.today().isoformat()}",
            "--thinking", "low", "--json", "-m", f"{system}\n\n{user}",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise LLMUnavailable(f"openclaw: {e}") from e
        if proc.returncode != 0:
            raise LLMUnavailable(f"openclaw exit {proc.returncode}: {proc.stderr[-300:]}")
        start = proc.stdout.find("{")
        try:
            envelope = json.loads(proc.stdout[start:])
            text = envelope["result"]["meta"]["finalAssistantVisibleText"]
        except (ValueError, KeyError, TypeError) as e:
            raise LLMUnavailable(f"openclaw: bad envelope: {e}") from e
        return parse_batch_text(text)
```

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && uv run pytest tests/test_llm_providers.py -v`
Expected: 4 passed. If `anthropic.APIStatusError(...)` construction signature differs in the installed SDK, check `uv run python -c "import anthropic, inspect; print(inspect.signature(anthropic.APIStatusError.__init__))"` and adapt the test's constructor call only.

- [ ] **Step 6: Commit**

```bash
git add backend/seekhunter/llm backend/tests/test_llm_providers.py
git commit -m "feat: add Anthropic Haiku and OpenClaw Codex scoring providers"
```

---

### Task 14: Notifier and message formatting

**Files:**
- Create: `backend/seekhunter/notify.py`
- Test: `backend/tests/test_notify.py`

- [ ] **Step 1: Write failing tests**

```python
import subprocess
from datetime import datetime

import pytest

from seekhunter.notify import DigestItem, Notifier, NotifyError, format_digest, format_recap


def item(i, score=80, flags=("flexible",)):
    return DigestItem(job_id=100 + i, score=score, title=f"Dev {i}", company="Acme", location="Adelaide SA",
                      work_type="contract", matched=["React", "TypeScript"], why="Strong React match",
                      url=f"https://www.seek.com.au/job/{i}", flags=list(flags))


def test_digest_format_and_split():
    msgs = format_digest([item(i) for i in range(12)], datetime(2026, 10, 17, 13, 0), "https://sh", [], extra=3)
    assert len(msgs) == 2
    assert msgs[0].startswith("🎯 SeekHunter · 12 new (13:00)")
    assert "#100 [80] Dev 0 — Acme · Adelaide SA · Contract 💼" in msgs[0]
    assert "Reply to OpenClaw" in msgs[-1]
    assert "React, TypeScript ✓" in msgs[0]
    assert '"Strong React match"' in msgs[0]
    assert "+3 more" in msgs[-1]
    assert msgs[-1].rstrip().endswith("→ https://sh")


def test_digest_mentions_degraded_sources_and_hours_flag():
    msgs = format_digest([item(1, flags=("flexible", "hours"))], datetime(2026, 10, 17, 9, 0), "https://sh",
                         ["jora"])
    assert "⚠️ hours" in msgs[0]
    assert "jora unavailable this run" in msgs[0]


def test_recap_format():
    text = format_recap([item(1), item(2, score=60)], excluded=4, day="Sat 17 Oct", public_url="https://sh")
    assert text.startswith("🎯 SeekHunter daily recap · Sat 17 Oct")
    assert "2 new jobs · 4 excluded" in text


def test_notifier_invokes_openclaw(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""))
    Notifier("openclaw", "123").send("hi")
    assert calls[0] == ["openclaw", "message", "send", "--channel", "telegram", "--target", "123",
                        "--message", "hi"]


def test_notifier_failure_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "nope"))
    with pytest.raises(NotifyError):
        Notifier("openclaw", "123").send("hi")


def test_notifier_dry_run_prints(capsys):
    Notifier("openclaw", "123", dry_run=True).send("hello")
    assert "hello" in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_notify.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `backend/seekhunter/notify.py`**

```python
import subprocess
from dataclasses import dataclass, field
from datetime import datetime

WORK_TYPE_LABELS = {"full_time": "Full time", "part_time": "Part time", "contract": "Contract",
                    "casual": "Casual", "unknown": "Type n/a"}
PER_MESSAGE = 10
REPLY_HINT = "💬 Reply to OpenClaw: \"save #id\", \"hide #id\", \"why #id?\""


class NotifyError(Exception):
    pass


@dataclass
class DigestItem:
    job_id: int
    score: int
    title: str
    company: str
    location: str
    work_type: str
    matched: list[str]
    why: str | None
    url: str
    flags: list[str] = field(default_factory=list)


def _format_item(it: DigestItem) -> str:
    badges = (" 💼" if "flexible" in it.flags else "") + (" ⚠️ hours" if "hours" in it.flags else "")
    line1 = f"#{it.job_id} [{it.score}] {it.title} — {it.company} · {it.location} · {WORK_TYPE_LABELS[it.work_type]}{badges}"
    details = []
    if it.matched:
        details.append(f"{', '.join(it.matched[:5])} ✓")
    if it.why:
        details.append(f'"{it.why}"')
    lines = [line1]
    if details:
        lines.append("   " + " · ".join(details))
    lines.append(f"   {it.url}")
    return "\n".join(lines)


def format_digest(items: list[DigestItem], when: datetime, public_url: str, degraded: list[str],
                  extra: int = 0) -> list[str]:
    header = f"🎯 SeekHunter · {len(items)} new ({when:%H:%M})"
    if degraded:
        header += "\n" + " ".join(f"⚠️ {s} unavailable this run" for s in degraded)
    chunks = [items[i : i + PER_MESSAGE] for i in range(0, len(items), PER_MESSAGE)] or [[]]
    messages = []
    for idx, chunk in enumerate(chunks):
        body = "\n".join(_format_item(it) for it in chunk)
        parts = [header if idx == 0 else f"🎯 SeekHunter · cont. ({idx + 1}/{len(chunks)})", body]
        if idx == len(chunks) - 1:
            if extra:
                parts.append(f"+{extra} more in the web UI")
            parts.append(f"→ {public_url}")
            parts.append(REPLY_HINT)
        messages.append("\n".join(p for p in parts if p))
    return messages


def format_recap(items: list[DigestItem], excluded: int, day: str, public_url: str) -> str:
    lines = [f"🎯 SeekHunter daily recap · {day}", f"{len(items)} new jobs · {excluded} excluded"]
    lines += [_format_item(it) for it in items[:15]]
    if len(items) > 15:
        lines.append(f"+{len(items) - 15} more in the web UI")
    lines.append(f"→ {public_url}")
    return "\n".join(lines)


class Notifier:
    def __init__(self, bin_path: str, target: str, dry_run: bool = False) -> None:
        self.bin_path, self.target, self.dry_run = bin_path, target, dry_run

    def send(self, text: str) -> None:
        if self.dry_run:
            print(f"--- [dry-run telegram → {self.target}] ---\n{text}\n")
            return
        cmd = [self.bin_path, "message", "send", "--channel", "telegram", "--target", self.target, "--message", text]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise NotifyError(str(e)) from e
        if proc.returncode != 0:
            raise NotifyError(f"exit {proc.returncode}: {proc.stderr[-300:]}")
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/test_notify.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/seekhunter/notify.py backend/tests/test_notify.py
git commit -m "feat: add Telegram digest formatting and OpenClaw notifier"
```

---

### Task 15: Run lock and pipeline

**Files:**
- Create: `backend/seekhunter/lock.py`, `backend/seekhunter/pipeline.py`
- Test: `backend/tests/test_pipeline.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from seekhunter import repo
from seekhunter.domain import JobData
from seekhunter.http import SourceBlocked
from seekhunter.llm.base import LLMScore
from seekhunter.lock import RunLocked, run_lock
from seekhunter.models import Job, JobEvaluation, Outbox
from seekhunter.notify import NotifyError
from seekhunter.pipeline import run_crawl, run_recap
from seekhunter.profile import Profile

PROFILE = Profile(skills={"React", "TypeScript"}, summary="s", titles=[], skill_lines=[], bullets=[])


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        repo.ensure_seed(s)
        for p in repo.list_search_profiles(s)[1:]:
            p.enabled = False
            s.add(p)
        s.commit()
        yield s


def jd(source, ext, title="React Developer", company="Acme", desc="React TypeScript", wt="contract"):
    return JobData(source=source, external_id=ext, title=title, company=company, location="Adelaide SA",
                   work_type=wt, url=f"https://x/{source}/{ext}", description_html=f"<p>{desc}</p>")


class FakeSource:
    def __init__(self, name, jobs, blocked=False):
        self.name, self.jobs, self.blocked = name, jobs, blocked
        self.client = type("C", (), {"request_count": 0, "blocked_count": 0})()
        self.detail_calls = 0

    def search(self, profile, max_pages):
        if self.blocked:
            raise SourceBlocked("403")
        return [JobData(**{**j.__dict__, "description_html": ""}) for j in self.jobs]

    def details(self, job):
        self.detail_calls += 1
        return next(j for j in self.jobs if j.external_id == job.external_id)


class FakeChain:
    def score_batch(self, profile, jobs):
        return {j.key: LLMScore(fit=50, why="ok") for j in jobs}, "fake"


class FakeNotifier:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, text):
        if self.fail:
            raise NotifyError("down")
        self.sent.append(text)


def test_full_run_excludes_dedupes_scores_and_notifies(session):
    seek = FakeSource("seek", [jd("seek", "1"), jd("seek", "2", company="Westpac"),
                               jd("seek", "3", desc="NV1 clearance required")])
    jora = FakeSource("jora", [jd("jora", "a"), jd("jora", "b", title="Vue Developer", company="Other")])
    notifier = FakeNotifier()
    report = run_crawl(session, {"seek": seek, "jora": jora}, FakeChain(), notifier, PROFILE, "https://sh")

    assert report.new_jobs == 5
    evals = {e.job_id: e for e in session.exec(select(JobEvaluation)).all()}
    jobs = {(j.source, j.external_id): j for j in session.exec(select(Job)).all()}
    assert evals[jobs[("seek", "2")].id].reasons == ["bank"]
    assert evals[jobs[("seek", "3")].id].reasons == ["clearance"]
    assert jobs[("jora", "a")].canonical_job_id == jobs[("seek", "1")].id
    good = evals[jobs[("seek", "1")].id]
    assert good.llm_score == 50 and good.llm_provider == "fake"
    assert good.final_score == round(0.6 * good.rule_score + 0.4 * 50)
    assert len(notifier.sent) == 1 and "2 new" in notifier.sent[0]

    again = FakeNotifier()
    report2 = run_crawl(session, {"seek": seek, "jora": jora}, FakeChain(), again, PROFILE, "https://sh")
    assert report2.new_jobs == 0 and again.sent == []
    assert seek.detail_calls == 3


def test_blocked_source_is_degraded_and_others_continue(session):
    seek = FakeSource("seek", [jd("seek", "1")])
    jora = FakeSource("jora", [], blocked=True)
    notifier = FakeNotifier()
    report = run_crawl(session, {"seek": seek, "jora": jora}, FakeChain(), notifier, PROFILE, "https://sh")
    assert report.source_status["jora"]["status"] == "degraded"
    assert report.source_status["seek"]["status"] == "ok"
    assert "jora unavailable" in notifier.sent[0]


def test_notify_failure_goes_to_outbox_and_flushes_next_run(session):
    seek = FakeSource("seek", [jd("seek", "1")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(fail=True), PROFILE, "https://sh")
    assert len(session.exec(select(Outbox)).all()) == 1
    ok = FakeNotifier()
    run_crawl(session, {"seek": seek}, FakeChain(), ok, PROFILE, "https://sh")
    assert len(ok.sent) == 1
    assert session.exec(select(Outbox)).one().sent_at is not None


def test_health_alert_after_three_all_failed_runs(session):
    blocked = {"seek": FakeSource("seek", [], blocked=True)}
    n = FakeNotifier()
    for _ in range(3):
        run_crawl(session, blocked, FakeChain(), n, PROFILE, "https://sh")
    assert sum("⚠️ SeekHunter" in m for m in n.sent) == 1
    run_crawl(session, blocked, FakeChain(), n, PROFILE, "https://sh")
    assert sum("⚠️ SeekHunter" in m for m in n.sent) == 1


def test_recap(session):
    seek = FakeSource("seek", [jd("seek", "1"), jd("seek", "2", company="Westpac")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    n = FakeNotifier()
    run_recap(session, n, "https://sh")
    assert "1 new jobs · 1 excluded" in n.sent[0]


def test_run_lock(tmp_path):
    with run_lock(tmp_path):
        with pytest.raises(RunLocked):
            with run_lock(tmp_path):
                pass
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_pipeline.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `backend/seekhunter/lock.py`**

```python
import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class RunLocked(Exception):
    pass


@contextmanager
def run_lock(data_dir: Path) -> Iterator[None]:
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(data_dir / "run.lock", "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise RunLocked("another run is in progress") from e
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
```


**Review addenda for Task 15 (from the Tasks 9–11 code review; implement these on top of the code below):**
1. Jobs stored by a crashed earlier run must not vanish. At the start of `_evaluate`'s input, also include jobs that have **no** `JobEvaluation` row and `canonical_job_id IS NULL` (add `repo.unevaluated_jobs(session) -> list[Job]` using an outer join where `JobEvaluation.id IS NULL`). Test: upsert a job without evaluation, run the pipeline with a source returning nothing new, and assert the job now has an evaluation and was notified.
2. In `_collect`, wrap each `source.details(data)` call in `except Exception` (not only `SourceBlocked`), log it, and record `st["error"] = f"details: ..."`, so one bad detail page doesn't abort the rest of the source.

- [ ] **Step 4: Implement `backend/seekhunter/pipeline.py`**

```python
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session

from seekhunter import repo
from seekhunter.filters import evaluate_exclusions
from seekhunter.http import SourceBlocked
from seekhunter.llm.base import LLMJobInput
from seekhunter.models import Job, JobEvaluation, Outbox, Run, utcnow
from seekhunter.notify import DigestItem, NotifyError, format_digest, format_recap
from seekhunter.profile import Profile
from seekhunter.scoring import blend, score_job

log = logging.getLogger(__name__)
TZ = ZoneInfo("Australia/Adelaide")
LLM_BATCH = 8


@dataclass
class RunReport:
    run_id: int
    new_jobs: int
    notified: int
    source_status: dict = field(default_factory=dict)


def _local(dt: datetime) -> datetime:
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ)


def digest_item(job: Job, ev: JobEvaluation) -> DigestItem:
    return DigestItem(job_id=job.id, score=ev.final_score, title=job.title, company=job.company, location=job.location,
                      work_type=job.work_type, matched=ev.matched_skills, why=ev.llm_note, url=job.url,
                      flags=ev.flags)


def _send(session: Session, notifier, text: str) -> bool:  # noqa: ANN001
    try:
        notifier.send(text)
        return True
    except NotifyError as e:
        log.error("notify failed: %s", e)
        session.add(Outbox(text=text, attempts=1, last_error=str(e)))
        session.commit()
        return False


def _flush_outbox(session: Session, notifier) -> None:  # noqa: ANN001
    for msg in repo.pending_outbox(session):
        try:
            notifier.send(msg.text)
            msg.sent_at = utcnow()
        except NotifyError as e:
            msg.attempts += 1
            msg.last_error = str(e)
        session.add(msg)
        session.commit()


def _collect(session: Session, sources: dict, settings) -> tuple[list[Job], dict]:  # noqa: ANN001
    status: dict = {}
    new_jobs: list[Job] = []
    profiles = repo.list_search_profiles(session, enabled_only=True)
    for name, source in sources.items():
        st = {"status": "ok", "found": 0, "new": 0, "error": None}
        try:
            for profile in profiles:
                if name not in profile.sources:
                    continue
                for data in source.search(profile, settings.max_pages_per_search):
                    st["found"] += 1
                    job, is_new = repo.upsert_job(session, data)
                    if not is_new:
                        continue
                    st["new"] += 1
                    new_jobs.append(job)
                    dup = repo.find_duplicate(session, job)
                    if dup:
                        job.canonical_job_id = dup
                        session.add(job)
                        session.commit()
                        continue
                    try:
                        repo.update_job_details(session, job, source.details(data))
                    except SourceBlocked as e:
                        st["error"] = f"details: {e}"
        except SourceBlocked as e:
            st["status"], st["error"] = "degraded", str(e)
        except Exception as e:  # parsing or network errors must not kill the other sources
            log.exception("source %s failed", name)
            st["status"], st["error"] = "degraded", f"{type(e).__name__}: {e}"
        st["requests"] = getattr(source.client, "request_count", 0)
        st["blocked"] = getattr(source.client, "blocked_count", 0)
        status[name] = st
    return new_jobs, status


def _evaluate(session: Session, jobs: list[Job], profile: Profile, settings, llm) -> str | None:  # noqa: ANN001
    pending: list[tuple[Job, object, object]] = []
    for job in jobs:
        if job.canonical_job_id:
            continue
        data = repo.to_jobdata(job)
        fr = evaluate_exclusions(data, settings)
        sr = score_job(data, profile.skills, settings)
        repo.save_evaluation(session, job.id, excluded=fr.excluded, reasons=fr.reasons, snippets=fr.snippets,
                             rule_score=sr.rule_score, llm_score=None, llm_note=None, llm_provider=None,
                             final_score=sr.rule_score, matched_skills=sr.matched_skills, flags=sr.flags)
        if not fr.excluded:
            pending.append((job, data, sr))

    used = None
    for i in range(0, len(pending), LLM_BATCH):
        batch = pending[i : i + LLM_BATCH]
        inputs = [LLMJobInput(key=str(j.id), title=d.title, company=d.company, work_type=d.work_type, text=d.text)
                  for j, d, _ in batch]
        scores, provider = llm.score_batch(profile, inputs)
        used = used or provider
        for job, _, sr in batch:
            s = scores.get(str(job.id))
            if s:
                repo.save_evaluation(session, job.id, llm_score=s.fit, llm_note=s.why, llm_provider=provider,
                                     final_score=blend(sr.rule_score, s.fit))
    return used


def _maybe_health_alert(session: Session, notifier, run: Run) -> None:  # noqa: ANN001
    recent = repo.recent_runs(session, "crawl", 3)
    if len(recent) < 3:
        return
    if not all(r.source_status and all(s["status"] != "ok" for s in r.source_status.values()) for r in recent):
        return
    last_alert = repo.recent_runs(session, "alert", 1)
    if last_alert and last_alert[0].started_at > utcnow() - timedelta(hours=24):
        return
    errors = "; ".join(f"{k}: {v.get('error')}" for k, v in run.source_status.items())
    _send(session, notifier, f"⚠️ SeekHunter: all sources failing for 3 runs. {errors}")
    session.add(Run(kind="alert", finished_at=utcnow()))
    session.commit()


def run_crawl(session: Session, sources: dict, llm, notifier, profile: Profile, public_url: str) -> RunReport:  # noqa: ANN001
    settings = repo.load_settings(session)
    run = Run(kind="crawl")
    session.add(run)
    session.commit()
    session.refresh(run)
    try:
        _flush_outbox(session, notifier)
        new_jobs, status = _collect(session, sources, settings)
        run.source_status, run.new_jobs = status, len(new_jobs)
        run.llm_provider = _evaluate(session, new_jobs, profile, settings, llm)

        now = utcnow()
        candidates = repo.notification_candidates(session, now)
        if candidates and settings.notify_enabled:
            top = candidates[: settings.max_notify_per_run]
            degraded = [k for k, v in status.items() if v["status"] != "ok"]
            for text in format_digest([digest_item(j, e) for j, e in top], _local(now), public_url, degraded,
                                      extra=len(candidates) - len(top)):
                _send(session, notifier, text)
            run.notified = len(top)
        if candidates:
            repo.mark_notified(session, [j.id for j, _ in candidates], now)
    except Exception as e:
        run.error = f"{type(e).__name__}: {e}"
        raise
    finally:
        run.finished_at = utcnow()
        session.add(run)
        session.commit()
    _maybe_health_alert(session, notifier, run)
    return RunReport(run_id=run.id, new_jobs=run.new_jobs, notified=run.notified, source_status=run.source_status)


def run_recap(session: Session, notifier, public_url: str) -> None:  # noqa: ANN001
    settings = repo.load_settings(session)
    if not settings.recap_enabled:
        return
    local_now = _local(utcnow())
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = start_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    rows = repo.list_jobs(session, view="active", since=since)
    excluded = repo.count_excluded_since(session, since)
    for text in format_recap([digest_item(j, e) for j, e in rows], excluded, f"{local_now:%a %d %b}", public_url):
        _send(session, notifier, text)
    session.add(Run(kind="recap", finished_at=utcnow(), new_jobs=len(rows)))
    session.commit()
```

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && uv run pytest tests/test_pipeline.py -v`
Expected: 6 passed. Common fixes: if the dedupe test fails because the Jora job is collected before SEEK, note that `sources` dict order is seek then jora, which the pipeline relies on (`build_sources` returns seek first).

- [ ] **Step 6: Run the whole backend suite**

Run: `cd backend && uv run pytest -q && uv run ruff check .`
Expected: all tests pass, ruff clean (fix any import-order findings with `uv run ruff check . --fix`).

- [ ] **Step 7: Commit**

```bash
git add backend/seekhunter/lock.py backend/seekhunter/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: add crawl/recap pipeline with dedupe, LLM blend, outbox, health alert"
```

---

### Task 16: CLI

**Files:**
- Create: `backend/seekhunter/cli.py`
- Test: `backend/tests/test_cli.py`

- [ ] **Step 1: Write failing test**

```python
from seekhunter import cli


def test_parser_commands():
    p = cli.build_parser()
    assert p.parse_args(["run", "--dry-run"]).dry_run is True
    assert p.parse_args(["recap"]).command == "recap"
    assert p.parse_args(["notify-test"]).command == "notify-test"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_cli.py -v`
Expected: FAIL, `ImportError`

- [ ] **Step 3: Implement `backend/seekhunter/cli.py`**

```python
import argparse
import json
import logging
import sys

from sqlmodel import Session

from seekhunter import repo
from seekhunter.config import get_env
from seekhunter.db import get_engine, init_db
from seekhunter.lock import RunLocked, run_lock
from seekhunter.notify import Notifier


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seekhunter")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="crawl, evaluate, notify")
    run.add_argument("--dry-run", action="store_true", help="print Telegram messages instead of sending")
    recap = sub.add_parser("recap", help="send today's recap")
    recap.add_argument("--dry-run", action="store_true")
    sub.add_parser("notify-test", help="send a test Telegram message")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    env = get_env()
    init_db()
    notifier = Notifier(env.openclaw_bin, env.telegram_target, dry_run=getattr(args, "dry_run", False))

    if args.command == "notify-test":
        notifier.send("🎯 SeekHunter test message ✅")
        return 0

    try:
        with run_lock(env.data_dir), Session(get_engine()) as session:
            repo.ensure_seed(session)
            if args.command == "recap":
                from seekhunter.pipeline import run_recap

                run_recap(session, notifier, env.public_url)
                return 0

            from seekhunter.llm.chain import build_chain
            from seekhunter.pipeline import run_crawl
            from seekhunter.profile import load_profile
            from seekhunter.sources import build_sources

            profile = load_profile(env.resume_dir)
            llm = build_chain(repo.load_settings(session), env)
            report = run_crawl(session, build_sources(), llm, notifier, profile, env.public_url)
            print(json.dumps(report.__dict__, default=str, indent=1))
            return 0
    except RunLocked:
        print("another run is in progress", file=sys.stderr)
        return 75


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/test_cli.py -v`
Expected: 1 passed

- [ ] **Step 5: Local live smoke test (network, no Telegram)**

Run: `cd backend && uv run seekhunter run --dry-run`
Expected: log lines for SEEK/Jora requests, a printed `--- [dry-run telegram → 1635495359] ---` block with jobs, and a JSON report with `seek` and `jora` statuses `ok` (Jora may be `degraded` if Cloudflare blocks your IP; that's acceptable if the message shows "jora unavailable this run"). No `ANTHROPIC_API_KEY` locally means rule-only scores. Then `rm -rf backend/data` to reset.

- [ ] **Step 6: Commit**

```bash
git add backend/seekhunter/cli.py backend/tests/test_cli.py
git commit -m "feat: add seekhunter CLI (run, recap, notify-test)"
```

---

### Task 16b: Rescore command (resume changes)

When `book-cv` changes, its deploy workflow syncs the LaTeX sections to `.50` and starts `seekhunter-rescore.service` (wired up in Tasks 24 and 26). This command re-runs exclusions and rule scoring for the last 7 days of jobs with the fresh profile. It keeps existing LLM scores, makes no LLM calls, and sends no notifications.

**Files:**
- Modify: `backend/seekhunter/lock.py`, `backend/seekhunter/repo.py`, `backend/seekhunter/pipeline.py`, `backend/seekhunter/cli.py`
- Test: `backend/tests/test_pipeline.py`, `backend/tests/test_cli.py`

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/test_pipeline.py`:
```python
from seekhunter.pipeline import run_rescore


def test_rescore_uses_new_profile_keeps_llm_and_sends_nothing(session):
    seek = FakeSource("seek", [jd("seek", "1", desc="React TypeScript Kotlin")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    ev = session.exec(select(JobEvaluation)).one()
    assert "Kotlin" not in ev.matched_skills

    richer = Profile(skills={"React", "TypeScript", "Kotlin"}, summary="s", titles=[], skill_lines=[], bullets=[])
    assert run_rescore(session, richer) == 1
    session.refresh(ev)
    assert "Kotlin" in ev.matched_skills
    assert ev.llm_score == 50
    assert ev.final_score == round(0.6 * ev.rule_score + 0.4 * 50)


def test_blocking_lock_waits(tmp_path):
    import threading
    import time

    order = []

    def holder():
        with run_lock(tmp_path):
            order.append("held")
            time.sleep(0.3)
        order.append("released")

    t = threading.Thread(target=holder)
    t.start()
    time.sleep(0.05)
    with run_lock(tmp_path, blocking=True):
        order.append("acquired")
    t.join()
    assert order == ["held", "released", "acquired"]
```

Append to `backend/tests/test_cli.py`:
```python
def test_parser_rescore():
    assert cli.build_parser().parse_args(["rescore"]).command == "rescore"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_pipeline.py tests/test_cli.py -v`
Expected: FAIL, `ImportError: cannot import name 'run_rescore'`

- [ ] **Step 3: Add `blocking` to `run_lock` in `backend/seekhunter/lock.py`**

Replace the function with:
```python
@contextmanager
def run_lock(data_dir: Path, blocking: bool = False) -> Iterator[None]:
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(data_dir / "run.lock", "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise RunLocked("another run is in progress") from e
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
```

- [ ] **Step 4: Add helpers to `backend/seekhunter/repo.py`**

```python
def jobs_since(session: Session, since: datetime) -> list[Job]:
    return list(session.exec(
        select(Job).where(Job.first_seen_at >= since, col(Job.canonical_job_id).is_(None))).all())


def get_evaluation(session: Session, job_id: int) -> JobEvaluation | None:
    return session.exec(select(JobEvaluation).where(JobEvaluation.job_id == job_id)).first()
```

- [ ] **Step 5: Add `run_rescore` to `backend/seekhunter/pipeline.py`**

```python
def run_rescore(session: Session, profile: Profile, days: int = 7) -> int:
    settings = repo.load_settings(session)
    count = 0
    for job in repo.jobs_since(session, utcnow() - timedelta(days=days)):
        data = repo.to_jobdata(job)
        fr = evaluate_exclusions(data, settings)
        sr = score_job(data, profile.skills, settings)
        existing = repo.get_evaluation(session, job.id)
        llm_score = existing.llm_score if existing else None
        repo.save_evaluation(session, job.id, excluded=fr.excluded, reasons=fr.reasons, snippets=fr.snippets,
                             rule_score=sr.rule_score, final_score=blend(sr.rule_score, llm_score),
                             matched_skills=sr.matched_skills, flags=sr.flags)
        count += 1
    session.add(Run(kind="rescore", finished_at=utcnow(), new_jobs=count))
    session.commit()
    return count
```

- [ ] **Step 6: Wire the CLI in `backend/seekhunter/cli.py`**

In `build_parser()` add after the `recap` parser:
```python
    sub.add_parser("rescore", help="re-score recent jobs after a resume change (no LLM, no notifications)")
```
In `main()`, replace `with run_lock(env.data_dir), Session(get_engine()) as session:` with:
```python
        with run_lock(env.data_dir, blocking=args.command == "rescore"), Session(get_engine()) as session:
```
and add right after `repo.ensure_seed(session)`:
```python
            if args.command == "rescore":
                from seekhunter.pipeline import run_rescore
                from seekhunter.profile import load_profile

                print(f"rescored {run_rescore(session, load_profile(env.resume_dir))} jobs")
                return 0
```

- [ ] **Step 7: Run to verify pass**

Run: `cd backend && uv run pytest -q && uv run ruff check .`
Expected: all passed, ruff clean.

- [ ] **Step 8: Commit**

```bash
git add backend/seekhunter backend/tests
git commit -m "feat: add rescore command for resume changes"
```

---

### Task 17: Security middleware

**Files:**
- Create: `backend/seekhunter/security.py`
- Test: `backend/tests/test_security.py`

- [ ] **Step 1: Write failing tests**

```python
from seekhunter.security import client_allowed

CIDRS = ["127.0.0.1/32", "192.168.4.0/24", "100.64.0.0/10"]
PUBLIC = ["180.150.112.113"]


def test_lan_and_tailscale_allowed_without_cf_header():
    assert client_allowed("192.168.4.20", None, CIDRS, PUBLIC)
    assert client_allowed("100.101.1.2", None, CIDRS, PUBLIC)
    assert not client_allowed("8.8.8.8", None, CIDRS, PUBLIC)


def test_tunnel_requests_judged_by_cf_ip():
    # cloudflared on .106 connects from the LAN, so the CF header must take precedence
    assert client_allowed("192.168.4.106", "180.150.112.113", CIDRS, PUBLIC)
    assert not client_allowed("192.168.4.106", "1.1.1.1", CIDRS, PUBLIC)
    assert client_allowed("192.168.4.106", "100.80.0.5", CIDRS, PUBLIC)
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_security.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `backend/seekhunter/security.py`**

```python
import ipaddress
import secrets

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse

from seekhunter.config import get_env


def _in_cidrs(ip: str, cidrs: list[str]) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in ipaddress.ip_network(c, strict=False) for c in cidrs)


def client_allowed(remote_ip: str, cf_ip: str | None, cidrs: list[str], public_ips: list[str]) -> bool:
    if cf_ip:
        return cf_ip in public_ips or _in_cidrs(cf_ip, cidrs)
    return _in_cidrs(remote_ip, cidrs)


async def ip_allowlist_middleware(request: Request, call_next):  # noqa: ANN001, ANN201
    if request.url.path == "/api/health":
        return await call_next(request)
    env = get_env()
    remote = request.client.host if request.client else ""
    if not client_allowed(remote, request.headers.get("cf-connecting-ip"), env.allowed_cidr_list,
                          env.allowed_public_ip_list):
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    return await call_next(request)


def require_write(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {get_env().api_write_token}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="write token required")
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/test_security.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/seekhunter/security.py backend/tests/test_security.py
git commit -m "feat: add IP allowlist middleware and write-token guard"
```

---

### Task 18: REST API + SPA serving

**Files:**
- Create: `backend/seekhunter/api.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from seekhunter import repo
from seekhunter.api import create_app
from seekhunter.config import get_env
from seekhunter.db import get_session
from seekhunter.domain import JobData

AUTH = {"Authorization": "Bearer t0k"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("API_WRITE_TOKEN", "t0k")
    monkeypatch.setenv("ALLOWED_CIDRS", "127.0.0.1/32,testclient/32")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    (tmp_path / "index.html").write_text("<html>spa</html>")
    get_env.cache_clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        repo.ensure_seed(s)
        job, _ = repo.upsert_job(s, JobData(source="seek", external_id="1", title="React Dev", company="Acme",
                                            location="Adelaide SA", work_type="contract", url="u",
                                            description_html="<p>React</p>"))
        repo.save_evaluation(s, job.id, excluded=False, reasons=[], snippets={}, rule_score=70, llm_score=None,
                             llm_note=None, llm_provider=None, final_score=70, matched_skills=["React"], flags=[])
        bad, _ = repo.upsert_job(s, JobData(source="seek", external_id="2", title="Dev", company="Westpac",
                                            location="Adelaide SA", work_type="contract", url="u2"))
        repo.save_evaluation(s, bad.id, excluded=True, reasons=["bank"], snippets={"bank": "Westpac"},
                             rule_score=60, llm_score=None, llm_note=None, llm_provider=None, final_score=60,
                             matched_skills=[], flags=[])

    def override():
        with Session(engine) as s:
            yield s

    app = create_app(init=False)
    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    get_env.cache_clear()


def test_health_and_spa(client):
    assert client.get("/api/health").json() == {"ok": True}
    assert "spa" in client.get("/jobs/123").text


def test_list_jobs_views(client):
    active = client.get("/api/jobs").json()
    assert [j["title"] for j in active] == ["React Dev"]
    assert active[0]["matched_skills"] == ["React"]
    excluded = client.get("/api/jobs", params={"view": "excluded"}).json()
    assert excluded[0]["reasons"] == ["bank"]


def test_job_detail_and_status_update_requires_token(client):
    job_id = client.get("/api/jobs").json()[0]["id"]
    assert "React" in client.get(f"/api/jobs/{job_id}").json()["description_html"]
    assert client.patch(f"/api/jobs/{job_id}", json={"status": "saved"}).status_code == 401
    r = client.patch(f"/api/jobs/{job_id}", json={"status": "saved", "notes": "apply Monday"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "saved"


def test_unexclude_with_allowlist(client):
    job_id = client.get("/api/jobs", params={"view": "excluded"}).json()[0]["id"]
    r = client.post(f"/api/jobs/{job_id}/unexclude", json={"allowlist_employer": True}, headers=AUTH)
    assert r.status_code == 200
    assert "Westpac" in client.get("/api/settings").json()["employer_allowlist"]
    assert len(client.get("/api/jobs").json()) == 2


def test_search_profile_crud_and_settings(client):
    r = client.post("/api/search-profiles", json={"name": "Mel", "keywords": "react", "location": "All Melbourne VIC",
                                                  "work_types": [], "sources": ["seek"], "enabled": True},
                    headers=AUTH)
    pid = r.json()["id"]
    assert any(p["id"] == pid for p in client.get("/api/search-profiles").json())
    assert client.put(f"/api/search-profiles/{pid}", json={**r.json(), "enabled": False},
                      headers=AUTH).json()["enabled"] is False
    assert client.delete(f"/api/search-profiles/{pid}", headers=AUTH).status_code == 204
    s = client.get("/api/settings").json()
    s["weights"]["full_time"] = 5
    assert client.put("/api/settings", json=s, headers=AUTH).json()["weights"]["full_time"] == 5


def test_runs_list(client):
    assert client.get("/api/runs").json() == []
```

Note: Starlette's TestClient reports the client host as `"testclient"`, which is not an IP, so `_in_cidrs` returns False. Make the test env allow it by having `client_allowed` treat the literal host `testclient` as allowed **only** when it appears verbatim in the CIDR list. Implement that by adding in `_in_cidrs`: `if ip in cidrs: return True` before parsing (also lets you list single hosts).

- [ ] **Step 2: Add the literal-host check to `security._in_cidrs`**

```python
def _in_cidrs(ip: str, cidrs: list[str]) -> bool:
    if ip in cidrs or f"{ip}/32" in cidrs:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in ipaddress.ip_network(c, strict=False) for c in cidrs if "/" in c and c[0].isdigit())
```

- [ ] **Step 3: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_api.py -v`
Expected: FAIL, `ModuleNotFoundError: seekhunter.api`

- [ ] **Step 4: Implement `backend/seekhunter/api.py`**

```python
import subprocess
import sys
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from seekhunter import repo
from seekhunter.config import get_env
from seekhunter.db import get_session, init_db
from seekhunter.models import Job, JobEvaluation, Run, SearchProfile
from seekhunter.notify import Notifier, NotifyError
from seekhunter.security import ip_allowlist_middleware, require_write
from seekhunter.settings_model import AppSettings


class JobOut(BaseModel):
    id: int
    source: str
    title: str
    company: str
    location: str
    work_type: str
    salary_label: str | None
    listed_at: datetime | None
    first_seen_at: datetime
    url: str
    status: str
    notes: str
    force_include: bool
    excluded: bool
    reasons: list[str]
    snippets: dict[str, str]
    rule_score: int
    llm_score: int | None
    llm_note: str | None
    final_score: int
    matched_skills: list[str]
    flags: list[str]


class JobDetailOut(JobOut):
    description_html: str
    teaser: str


class JobPatch(BaseModel):
    status: str | None = None
    notes: str | None = None


class UnexcludeIn(BaseModel):
    allowlist_employer: bool = False


class SearchProfileIn(BaseModel):
    name: str
    keywords: str
    location: str
    work_types: list[str] = []
    sources: list[str] = ["seek", "jora"]
    enabled: bool = True


def _job_out(job: Job, ev: JobEvaluation, detail: bool = False) -> JobOut:
    base = dict(
        id=job.id, source=job.source, title=job.title, company=job.company, location=job.location,
        work_type=job.work_type, salary_label=job.salary_label, listed_at=job.listed_at,
        first_seen_at=job.first_seen_at, url=job.url, status=job.status, notes=job.notes,
        force_include=job.force_include, excluded=ev.excluded, reasons=ev.reasons, snippets=ev.snippets,
        rule_score=ev.rule_score, llm_score=ev.llm_score, llm_note=ev.llm_note, final_score=ev.final_score,
        matched_skills=ev.matched_skills, flags=ev.flags,
    )
    if detail:
        return JobDetailOut(**base, description_html=job.description_html, teaser=job.teaser)
    return JobOut(**base)


def _get_job(session: Session, job_id: int) -> tuple[Job, JobEvaluation]:
    job = session.get(Job, job_id)
    ev = session.exec(select(JobEvaluation).where(JobEvaluation.job_id == job_id)).first()
    if not job or not ev:
        raise HTTPException(404, "job not found")
    return job, ev


def create_app(init: bool = True) -> FastAPI:
    env = get_env()
    if init:
        init_db()
        from seekhunter.db import get_engine

        with Session(get_engine()) as s:
            repo.ensure_seed(s)

    app = FastAPI(title="SeekHunter")
    app.middleware("http")(ip_allowlist_middleware)
    write = [Depends(require_write)]

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/jobs", response_model=list[JobOut])
    def list_jobs(view: str = "active", status: str | None = None, work_type: str | None = None,
                  source: str | None = None, q: str | None = None, limit: int = 200, offset: int = 0,
                  session: Session = Depends(get_session)):
        rows = repo.list_jobs(session, view=view, status=status, work_type=work_type, source=source, q=q,
                              limit=limit, offset=offset)
        return [_job_out(j, e) for j, e in rows]

    @app.get("/api/jobs/{job_id}", response_model=JobDetailOut)
    def get_job(job_id: int, session: Session = Depends(get_session)):
        return _job_out(*_get_job(session, job_id), detail=True)

    @app.patch("/api/jobs/{job_id}", response_model=JobOut, dependencies=write)
    def patch_job(job_id: int, body: JobPatch, session: Session = Depends(get_session)):
        job, ev = _get_job(session, job_id)
        if body.status is not None:
            if body.status not in {"new", "saved", "applied", "hidden"}:
                raise HTTPException(422, "invalid status")
            job.status = body.status
        if body.notes is not None:
            job.notes = body.notes
        session.add(job)
        session.commit()
        return _job_out(job, ev)

    @app.post("/api/jobs/{job_id}/unexclude", response_model=JobOut, dependencies=write)
    def unexclude(job_id: int, body: UnexcludeIn, session: Session = Depends(get_session)):
        job, ev = _get_job(session, job_id)
        job.force_include = True
        session.add(job)
        session.commit()
        if body.allowlist_employer and job.company:
            settings = repo.load_settings(session)
            if job.company not in settings.employer_allowlist:
                settings.employer_allowlist.append(job.company)
                repo.save_settings(session, settings)
        return _job_out(job, ev)

    @app.get("/api/search-profiles", response_model=list[SearchProfile])
    def list_profiles(session: Session = Depends(get_session)):
        return repo.list_search_profiles(session)

    @app.post("/api/search-profiles", response_model=SearchProfile, dependencies=write)
    def create_profile(body: SearchProfileIn, session: Session = Depends(get_session)):
        profile = SearchProfile(**body.model_dump())
        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile

    @app.put("/api/search-profiles/{pid}", response_model=SearchProfile, dependencies=write)
    def update_profile(pid: int, body: SearchProfileIn, session: Session = Depends(get_session)):
        profile = session.get(SearchProfile, pid)
        if not profile:
            raise HTTPException(404, "not found")
        for k, v in body.model_dump().items():
            setattr(profile, k, v)
        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile

    @app.delete("/api/search-profiles/{pid}", status_code=204, dependencies=write)
    def delete_profile(pid: int, session: Session = Depends(get_session)):
        profile = session.get(SearchProfile, pid)
        if profile:
            session.delete(profile)
            session.commit()
        return Response(status_code=204)

    @app.get("/api/settings", response_model=AppSettings)
    def get_settings(session: Session = Depends(get_session)):
        return repo.load_settings(session)

    @app.put("/api/settings", response_model=AppSettings, dependencies=write)
    def put_settings(body: AppSettings, session: Session = Depends(get_session)):
        repo.save_settings(session, body)
        return body

    @app.get("/api/runs", response_model=list[Run])
    def list_runs(session: Session = Depends(get_session)):
        return repo.recent_runs(session, "crawl", 50)

    @app.post("/api/runs", status_code=202, dependencies=write)
    def trigger_run() -> dict:
        subprocess.Popen([sys.executable, "-m", "seekhunter.cli", "run"], start_new_session=True)
        return {"started": True}

    @app.post("/api/notify/test", dependencies=write)
    def notify_test() -> dict:
        try:
            Notifier(env.openclaw_bin, env.telegram_target).send("🎯 SeekHunter test message ✅")
        except NotifyError as e:
            raise HTTPException(502, str(e)) from e
        return {"sent": True}

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        static = env.static_dir.resolve()
        candidate = (static / path).resolve()
        if path and candidate.is_file() and static in candidate.parents:
            return FileResponse(candidate)
        index = static / "index.html"
        if not index.exists():
            raise HTTPException(404, "frontend not built")
        return FileResponse(index)

    return app
```

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && uv run pytest tests/test_api.py -v`
Expected: 6 passed

- [ ] **Step 6: Full suite + lint**

Run: `cd backend && uv run pytest -q && uv run ruff check .`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add backend/seekhunter/api.py backend/seekhunter/security.py backend/tests/test_api.py
git commit -m "feat: add REST API, run trigger, and SPA serving"
```

---

### Task 18b: Agent-friendly endpoints (for the OpenClaw skill)

OpenClaw talks to SeekHunter through the API (Task 24b installs the skill). Agents work best with compact plain text, so add two read endpoints that return `text/plain`.

**Files:**
- Modify: `backend/seekhunter/api.py`, `backend/seekhunter/notify.py`
- Test: `backend/tests/test_api.py`, `backend/tests/test_notify.py`

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/test_notify.py`:
```python
from seekhunter.notify import format_brief


def test_format_brief():
    text = format_brief(
        job_id=7, title="React Dev", company="Acme", location="Adelaide SA", work_type="contract",
        salary="$90/h", score=80, rule_score=75, llm_score=88, llm_note="Strong React",
        matched=["React"], missing=["Kotlin"], flags=["flexible"], reasons=[], status="new",
        url="https://x/7", description="We need React. " * 500,
    )
    assert text.startswith("#7 React Dev — Acme")
    assert "Matched: React" in text and "Missing: Kotlin" in text
    assert "AI 88" in text
    assert len(text) < 5000
```

Append to `backend/tests/test_api.py` (uses the existing `client` fixture; the `RESUME_DIR` env must point at the test resume fixture, so add `monkeypatch.setenv("RESUME_DIR", str(Path(__file__).parent / "fixtures" / "resume"))` to the fixture, with `from pathlib import Path` at the top):
```python
def test_brief_and_summary_are_plain_text(client):
    job_id = client.get("/api/jobs").json()[0]["id"]
    r = client.get(f"/api/jobs/{job_id}/brief")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert r.text.startswith(f"#{job_id} React Dev")
    s = client.get("/api/summary", params={"hours": 24})
    assert s.headers["content-type"].startswith("text/plain")
    assert f"#{job_id}" in s.text
    assert client.get("/api/jobs/99999/brief").status_code == 404
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_notify.py tests/test_api.py -v`
Expected: FAIL, `ImportError: cannot import name 'format_brief'`

- [ ] **Step 3: Add `format_brief` to `backend/seekhunter/notify.py`**

```python
def format_brief(*, job_id: int, title: str, company: str, location: str, work_type: str, salary: str | None,
                 score: int, rule_score: int, llm_score: int | None, llm_note: str | None, matched: list[str],
                 missing: list[str], flags: list[str], reasons: list[str], status: str, url: str,
                 description: str) -> str:
    lines = [
        f"#{job_id} {title} — {company} · {location} · {WORK_TYPE_LABELS.get(work_type, work_type)}"
        + (f" · {salary}" if salary else ""),
        f"Score {score} (rules {rule_score}" + (f", AI {llm_score}" if llm_score is not None else "") + ")"
        + f" · status {status}",
    ]
    if llm_note:
        lines.append(f"AI note: {llm_note}")
    lines.append(f"Matched: {', '.join(matched) or '-'}")
    lines.append(f"Missing: {', '.join(missing) or '-'}")
    if flags:
        lines.append(f"Flags: {', '.join(flags)}")
    if reasons:
        lines.append(f"Excluded for: {', '.join(reasons)}")
    lines.append(f"URL: {url}")
    lines.append("")
    lines.append(description[:3500])
    return "\n".join(lines)
```

- [ ] **Step 4: Add the endpoints to `backend/seekhunter/api.py`**

Add imports: `from datetime import timedelta`, `from fastapi.responses import PlainTextResponse`, `from seekhunter.models import utcnow`, `from seekhunter.notify import format_brief`, `from seekhunter.profile import load_profile`, `from seekhunter.skills import extract_skills`, and `digest_item` from `seekhunter.pipeline`. Inside `create_app`, before the SPA catch-all route:

```python
    @app.get("/api/jobs/{job_id}/brief", response_class=PlainTextResponse)
    def job_brief(job_id: int, session: Session = Depends(get_session)):
        job, ev = _get_job(session, job_id)
        data = repo.to_jobdata(job)
        try:
            profile_skills = load_profile(env.resume_dir).skills
        except FileNotFoundError:
            profile_skills = set()
        missing = sorted(extract_skills(f"{job.title} {data.text}") - profile_skills)
        return format_brief(
            job_id=job.id, title=job.title, company=job.company, location=job.location, work_type=job.work_type,
            salary=job.salary_label, score=ev.final_score, rule_score=ev.rule_score, llm_score=ev.llm_score,
            llm_note=ev.llm_note, matched=ev.matched_skills, missing=missing, flags=ev.flags,
            reasons=ev.reasons, status=job.status, url=job.url, description=data.text,
        )

    @app.get("/api/summary", response_class=PlainTextResponse)
    def summary(hours: int = 24, session: Session = Depends(get_session)):
        rows = repo.list_jobs(session, view="active", since=utcnow() - timedelta(hours=hours), limit=30)
        if not rows:
            return f"No new jobs in the last {hours}h."
        return "\n".join(
            f"#{j.id} [{e.final_score}] {j.title} — {j.company} · {j.location} · {j.work_type} · {j.status}"
            for j, e in rows
        )
```

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && uv run pytest -q && uv run ruff check .`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add backend
git commit -m "feat: add plain-text brief and summary endpoints for agents"
```

---

### Task 19: Frontend scaffold (Vite + Tailwind + shadcn + API client)

**Files:**
- Create: `frontend/` (Vite template), `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`, `frontend/src/lib/api.test.ts`, `frontend/vite.config.ts`
- Modify: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/tsconfig.app.json`, `frontend/src/index.css`

- [ ] **Step 1: Scaffold**

Run:
```bash
cd /Users/book/Documents/code/seek-hunter
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install
npm install react-router-dom @tanstack/react-query dompurify tailwindcss @tailwindcss/vite
npm install -D @types/dompurify @types/node vitest jsdom @testing-library/react @testing-library/jest-dom
```
Expected: `frontend/` with `src/App.tsx`, `package.json`.

- [ ] **Step 2: Replace `frontend/vite.config.ts`**

```ts
/// <reference types="vitest/config" />
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: { proxy: { "/api": "http://localhost:8090" } },
  test: { environment: "jsdom", globals: true },
});
```

- [ ] **Step 3: Add the path alias to both `frontend/tsconfig.json` and `frontend/tsconfig.app.json`**

In each file's `compilerOptions` add:
```json
"baseUrl": ".",
"paths": { "@/*": ["./src/*"] }
```
(`tsconfig.json` may only contain `files`/`references`; add a `compilerOptions` object to it if absent. shadcn reads the root file.)

- [ ] **Step 4: Replace `frontend/src/index.css`**

```css
@import "tailwindcss";
```

- [ ] **Step 5: Initialise shadcn and add components**

Run:
```bash
cd frontend
npx shadcn@latest init -d
npx shadcn@latest add button badge table input textarea select switch sheet card tabs label dialog sonner
```
Expected: `components.json`, `src/components/ui/*.tsx`, `src/lib/utils.ts`; `src/index.css` gains theme variables.

- [ ] **Step 6: Add test script to `frontend/package.json`**

In `"scripts"` add: `"test": "vitest run"`.

- [ ] **Step 7: Create `frontend/src/lib/types.ts`**

```ts
export type WorkType = "full_time" | "part_time" | "contract" | "casual" | "unknown";
export type JobStatus = "new" | "saved" | "applied" | "hidden";

export interface Job {
  id: number;
  source: "seek" | "jora";
  title: string;
  company: string;
  location: string;
  work_type: WorkType;
  salary_label: string | null;
  listed_at: string | null;
  first_seen_at: string;
  url: string;
  status: JobStatus;
  notes: string;
  force_include: boolean;
  excluded: boolean;
  reasons: string[];
  snippets: Record<string, string>;
  rule_score: number;
  llm_score: number | null;
  llm_note: string | null;
  final_score: number;
  matched_skills: string[];
  flags: string[];
}

export interface JobDetail extends Job {
  description_html: string;
  teaser: string;
}

export interface SearchProfile {
  id?: number;
  name: string;
  keywords: string;
  location: string;
  work_types: WorkType[];
  sources: ("seek" | "jora")[];
  enabled: boolean;
}

export interface Weights {
  flexible_work: number;
  full_time: number;
  skill_max: number;
  role_max: number;
  skill_saturation: number;
}

export interface AppSettings {
  defence_employers: string[];
  bank_employers: string[];
  employer_allowlist: string[];
  clearance_patterns: string[];
  citizenship_patterns: string[];
  defence_keywords: string[];
  bank_keywords: string[];
  exclude_fintech: boolean;
  fintech_keywords: string[];
  role_boost_terms: string[];
  role_penalty_terms: string[];
  weights: Weights;
  llm_enabled: boolean;
  llm_providers: string[];
  notify_enabled: boolean;
  recap_enabled: boolean;
  max_pages_per_search: number;
  max_notify_per_run: number;
}

export interface SourceStatus {
  status: "ok" | "degraded";
  found: number;
  new: number;
  requests: number;
  blocked: number;
  error: string | null;
}

export interface Run {
  id: number;
  kind: string;
  started_at: string;
  finished_at: string | null;
  source_status: Record<string, SourceStatus>;
  new_jobs: number;
  notified: number;
  llm_provider: string | null;
  error: string | null;
}

export const WORK_TYPE_LABEL: Record<WorkType, string> = {
  full_time: "Full time",
  part_time: "Part time",
  contract: "Contract",
  casual: "Casual",
  unknown: "n/a",
};
```

- [ ] **Step 8: Write failing test `frontend/src/lib/api.test.ts`**

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, getToken, setToken } from "./api";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("api", () => {
  it("sends bearer token on writes and none on reads", async () => {
    setToken("abc");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "content-type": "application/json" } }),
    );
    await api.jobs({ view: "active" });
    await api.patchJob(1, { status: "saved" });
    const [readUrl, readInit] = fetchMock.mock.calls[0];
    expect(String(readUrl)).toBe("/api/jobs?view=active");
    expect((readInit?.headers as Record<string, string>).Authorization).toBeUndefined();
    const [, writeInit] = fetchMock.mock.calls[1];
    expect((writeInit?.headers as Record<string, string>).Authorization).toBe("Bearer abc");
    expect(getToken()).toBe("abc");
  });

  it("throws ApiError with status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("nope", { status: 401 }));
    await expect(api.patchJob(1, { status: "saved" })).rejects.toMatchObject({ status: 401 });
  });
});
```

- [ ] **Step 9: Run to verify fail**

Run: `cd frontend && npm test`
Expected: FAIL, cannot resolve `./api`

- [ ] **Step 10: Implement `frontend/src/lib/api.ts`**

```ts
import type { AppSettings, Job, JobDetail, JobStatus, Run, SearchProfile } from "./types";

const TOKEN_KEY = "seekhunter.token";

export const getToken = () => localStorage.getItem(TOKEN_KEY) ?? "";
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t);

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (method !== "GET") headers.Authorization = `Bearer ${getToken()}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const qs = (params: Record<string, string | undefined>) => {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== "") as [string, string][];
  return entries.length ? `?${new URLSearchParams(entries).toString()}` : "";
};

export const api = {
  jobs: (p: { view?: string; status?: string; work_type?: string; source?: string; q?: string }) =>
    request<Job[]>("GET", `/api/jobs${qs(p)}`),
  job: (id: number) => request<JobDetail>("GET", `/api/jobs/${id}`),
  patchJob: (id: number, body: { status?: JobStatus; notes?: string }) =>
    request<Job>("PATCH", `/api/jobs/${id}`, body),
  unexclude: (id: number, allowlist_employer: boolean) =>
    request<Job>("POST", `/api/jobs/${id}/unexclude`, { allowlist_employer }),
  profiles: () => request<SearchProfile[]>("GET", "/api/search-profiles"),
  createProfile: (p: SearchProfile) => request<SearchProfile>("POST", "/api/search-profiles", p),
  updateProfile: (p: SearchProfile) => request<SearchProfile>("PUT", `/api/search-profiles/${p.id}`, p),
  deleteProfile: (id: number) => request<void>("DELETE", `/api/search-profiles/${id}`),
  settings: () => request<AppSettings>("GET", "/api/settings"),
  saveSettings: (s: AppSettings) => request<AppSettings>("PUT", "/api/settings", s),
  runs: () => request<Run[]>("GET", "/api/runs"),
  triggerRun: () => request<{ started: boolean }>("POST", "/api/runs"),
  notifyTest: () => request<{ sent: boolean }>("POST", "/api/notify/test"),
};
```

- [ ] **Step 11: Run to verify pass**

Run: `cd frontend && npm test`
Expected: 2 passed

- [ ] **Step 12: Commit**

```bash
git add frontend
git commit -m "feat: scaffold React frontend with typed API client"
```

---

### Task 20: Layout, routing, token dialog, score badge

**Files:**
- Create: `frontend/src/components/Layout.tsx`, `frontend/src/components/TokenDialog.tsx`, `frontend/src/components/ScoreBadge.tsx`, `frontend/src/components/ScoreBadge.test.tsx`
- Modify: `frontend/src/main.tsx`, `frontend/src/App.tsx`
- Delete: `frontend/src/App.css`, `frontend/src/assets/react.svg`

- [ ] **Step 1: Write failing test `frontend/src/components/ScoreBadge.test.tsx`**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScoreBadge } from "./ScoreBadge";

describe("ScoreBadge", () => {
  it("shows score with tone class", () => {
    render(<ScoreBadge score={82} />);
    const el = screen.getByText("82");
    expect(el.className).toContain("bg-emerald");
  });
  it("uses muted tone for low scores", () => {
    render(<ScoreBadge score={30} />);
    expect(screen.getByText("30").className).toContain("bg-muted");
  });
});
```

- [ ] **Step 2: Run to verify fail**

Run: `cd frontend && npm test`
Expected: FAIL, cannot resolve `./ScoreBadge`

- [ ] **Step 3: Implement `frontend/src/components/ScoreBadge.tsx`**

```tsx
import { cn } from "@/lib/utils";

export function ScoreBadge({ score }: { score: number }) {
  const tone =
    score >= 75
      ? "bg-emerald-600 text-white"
      : score >= 55
        ? "bg-amber-500 text-white"
        : "bg-muted text-muted-foreground";
  return (
    <span className={cn("inline-flex h-7 w-10 items-center justify-center rounded-md text-sm font-semibold", tone)}>
      {score}
    </span>
  );
}
```

- [ ] **Step 4: Implement `frontend/src/components/TokenDialog.tsx`**

```tsx
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { getToken, setToken } from "@/lib/api";

export function TokenDialog() {
  const [value, setValue] = useState(getToken());
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant={getToken() ? "ghost" : "outline"} size="sm">
          {getToken() ? "🔑 Token set" : "Set write token"}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Write token</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">
          Needed to change statuses, searches and settings. Find it as API_WRITE_TOKEN in /opt/seek-hunter/.env.
        </p>
        <Input type="password" value={value} onChange={(e) => setValue(e.target.value)} />
        <Button
          onClick={() => {
            setToken(value.trim());
            setOpen(false);
          }}
        >
          Save
        </Button>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 5: Implement `frontend/src/components/Layout.tsx`**

```tsx
import { NavLink, Outlet } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { cn } from "@/lib/utils";
import { TokenDialog } from "./TokenDialog";

const links = [
  { to: "/", label: "Jobs" },
  { to: "/excluded", label: "Excluded" },
  { to: "/searches", label: "Searches" },
  { to: "/settings", label: "Settings" },
  { to: "/runs", label: "Runs" },
];

export function Layout() {
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
          <span className="font-semibold">🎯 SeekHunter</span>
          <nav className="flex gap-1">
            {links.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.to === "/"}
                className={({ isActive }) =>
                  cn("rounded-md px-3 py-1.5 text-sm", isActive ? "bg-muted font-medium" : "text-muted-foreground")
                }
              >
                {l.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto">
            <TokenDialog />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
      <Toaster />
    </div>
  );
}
```

- [ ] **Step 6: Replace `frontend/src/App.tsx`** (pages are created in Tasks 21–23; create placeholder files now so this compiles)

```tsx
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { JobsPage } from "@/pages/JobsPage";
import { RunsPage } from "@/pages/RunsPage";
import { SearchesPage } from "@/pages/SearchesPage";
import { SettingsPage } from "@/pages/SettingsPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<JobsPage view="active" />} />
          <Route path="excluded" element={<JobsPage view="excluded" />} />
          <Route path="searches" element={<SearchesPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="runs" element={<RunsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
```

Create temporary placeholders (each replaced in later tasks):
- `frontend/src/pages/JobsPage.tsx`: `export function JobsPage({ view }: { view: "active" | "excluded" }) { return <div>{view}</div>; }`
- `frontend/src/pages/SearchesPage.tsx`: `export function SearchesPage() { return <div>searches</div>; }`
- `frontend/src/pages/SettingsPage.tsx`: `export function SettingsPage() { return <div>settings</div>; }`
- `frontend/src/pages/RunsPage.tsx`: `export function RunsPage() { return <div>runs</div>; }`

- [ ] **Step 7: Replace `frontend/src/main.tsx`**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, retry: 1 } } });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
```

- [ ] **Step 8: Delete the template files and verify**

Run: `cd frontend && rm -f src/App.css src/assets/react.svg && npm test && npm run build`
Expected: tests pass, build succeeds with `dist/index.html`.

- [ ] **Step 9: Commit**

```bash
git add -A frontend
git commit -m "feat: add app layout, routing, token dialog, score badge"
```

---

### Task 21: Jobs and Excluded pages

**Files:**
- Create: `frontend/src/components/JobTable.tsx`, `frontend/src/components/JobDrawer.tsx`
- Modify: `frontend/src/pages/JobsPage.tsx`

- [ ] **Step 1: Implement `frontend/src/components/JobTable.tsx`**

```tsx
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { type Job, WORK_TYPE_LABEL } from "@/lib/types";
import { ScoreBadge } from "./ScoreBadge";

const since = (iso: string) => {
  const h = Math.round((Date.now() - new Date(iso.endsWith("Z") ? iso : `${iso}Z`).getTime()) / 3_600_000);
  return h < 24 ? `${h}h` : `${Math.round(h / 24)}d`;
};

export function JobTable({ jobs, view, onSelect }: { jobs: Job[]; view: "active" | "excluded"; onSelect: (j: Job) => void }) {
  if (!jobs.length) return <p className="py-12 text-center text-muted-foreground">No jobs yet.</p>;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-14">Score</TableHead>
          <TableHead>Role</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>{view === "excluded" ? "Reason" : "Skills"}</TableHead>
          <TableHead className="w-16">Seen</TableHead>
          <TableHead className="w-20">Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {jobs.map((j) => (
          <TableRow key={j.id} className="cursor-pointer" onClick={() => onSelect(j)}>
            <TableCell>
              <ScoreBadge score={j.final_score} />
            </TableCell>
            <TableCell>
              <div className="font-medium">{j.title}</div>
              <div className="text-sm text-muted-foreground">
                {j.company} · {j.location} · {j.source}
              </div>
            </TableCell>
            <TableCell>
              <Badge variant={j.flags.includes("flexible") ? "default" : "secondary"}>{WORK_TYPE_LABEL[j.work_type]}</Badge>
              {j.flags.includes("hours") && <span className="ml-1" title="Stated hours may exceed visa limit">⚠️</span>}
            </TableCell>
            <TableCell className="max-w-xs text-sm">
              {view === "excluded" ? j.reasons.join(", ") : j.matched_skills.slice(0, 5).join(", ")}
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">{since(j.first_seen_at)}</TableCell>
            <TableCell className="text-sm">{j.status}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
```

- [ ] **Step 2: Implement `frontend/src/components/JobDrawer.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import DOMPurify from "dompurify";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { type Job, type JobStatus, WORK_TYPE_LABEL } from "@/lib/types";
import { ScoreBadge } from "./ScoreBadge";

function highlight(html: string, skills: string[]): string {
  const clean = DOMPurify.sanitize(html);
  if (!skills.length) return clean;
  const escaped = skills.map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const re = new RegExp(`(?<![\\w#+.])(${escaped.join("|")})(?![\\w#+])`, "gi");
  return clean.replace(/>([^<]+)</g, (_m, text: string) => `>${text.replace(re, "<mark>$1</mark>")}<`);
}

export function JobDrawer({ job, onClose }: { job: Job | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["job", job?.id], queryFn: () => api.job(job!.id), enabled: !!job });
  const [notes, setNotes] = useState("");
  useEffect(() => setNotes(data?.notes ?? ""), [data?.notes]);

  const done = (msg: string) => {
    toast.success(msg);
    qc.invalidateQueries({ queryKey: ["jobs"] });
    qc.invalidateQueries({ queryKey: ["job", job?.id] });
  };
  const fail = (e: Error) => toast.error(e.message.includes("401") ? "Set the write token first" : e.message);
  const patch = useMutation({
    mutationFn: (body: { status?: JobStatus; notes?: string }) => api.patchJob(job!.id, body),
    onSuccess: () => done("Saved"),
    onError: fail,
  });
  const unexclude = useMutation({
    mutationFn: (allow: boolean) => api.unexclude(job!.id, allow),
    onSuccess: () => {
      done("Moved to jobs");
      onClose();
    },
    onError: fail,
  });

  return (
    <Sheet open={!!job} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        {job && (
          <>
            <SheetHeader>
              <SheetTitle className="flex items-start gap-3">
                <ScoreBadge score={job.final_score} />
                <span>{job.title}</span>
              </SheetTitle>
              <p className="text-sm text-muted-foreground">
                {job.company} · {job.location} · {WORK_TYPE_LABEL[job.work_type]}
                {job.salary_label ? ` · ${job.salary_label}` : ""}
              </p>
            </SheetHeader>
            <div className="space-y-4 px-4 pb-8">
              <div className="flex flex-wrap gap-1">
                {job.matched_skills.map((s) => (
                  <Badge key={s} variant="secondary">
                    {s}
                  </Badge>
                ))}
              </div>
              <p className="text-sm">
                Rule {job.rule_score}
                {job.llm_score !== null && ` · AI ${job.llm_score}`}
                {job.llm_note && <span className="text-muted-foreground"> — “{job.llm_note}”</span>}
              </p>
              {job.excluded && (
                <div className="rounded-md border border-destructive/40 p-3 text-sm">
                  {Object.entries(job.snippets).map(([reason, snippet]) => (
                    <p key={reason}>
                      <b>{reason}</b>: …{snippet}…
                    </p>
                  ))}
                  <div className="mt-2 flex gap-2">
                    <Button size="sm" variant="outline" onClick={() => unexclude.mutate(false)}>
                      Un-exclude
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => unexclude.mutate(true)}>
                      Un-exclude + allowlist {job.company}
                    </Button>
                  </div>
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                <Button asChild size="sm">
                  <a href={job.url} target="_blank" rel="noreferrer">
                    Open on {job.source === "seek" ? "SEEK" : "Jora"}
                  </a>
                </Button>
                {(["saved", "applied", "hidden", "new"] as JobStatus[]).map((s) => (
                  <Button key={s} size="sm" variant={job.status === s ? "default" : "outline"} onClick={() => patch.mutate({ status: s })}>
                    {s}
                  </Button>
                ))}
              </div>
              <div className="space-y-2">
                <Textarea placeholder="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
                <Button size="sm" variant="secondary" onClick={() => patch.mutate({ notes })}>
                  Save notes
                </Button>
              </div>
              <article
                className="prose prose-sm max-w-none [&_mark]:bg-yellow-200"
                dangerouslySetInnerHTML={{ __html: highlight(data?.description_html || data?.teaser || "", job.matched_skills) }}
              />
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
```

- [ ] **Step 3: Replace `frontend/src/pages/JobsPage.tsx`**

```tsx
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { JobDrawer } from "@/components/JobDrawer";
import { JobTable } from "@/components/JobTable";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api } from "@/lib/api";
import type { Job } from "@/lib/types";

const ALL = "all";

export function JobsPage({ view }: { view: "active" | "excluded" }) {
  const [q, setQ] = useState("");
  const [workType, setWorkType] = useState(ALL);
  const [status, setStatus] = useState(ALL);
  const [source, setSource] = useState(ALL);
  const [selected, setSelected] = useState<Job | null>(null);
  const params = {
    view,
    q,
    work_type: workType === ALL ? undefined : workType,
    status: status === ALL ? undefined : status,
    source: source === ALL ? undefined : source,
  };
  const { data = [], isLoading } = useQuery({ queryKey: ["jobs", params], queryFn: () => api.jobs(params) });

  const select = (value: string, onChange: (v: string) => void, options: [string, string][], placeholder: string) => (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="w-36">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {options.map(([v, label]) => (
          <SelectItem key={v} value={v}>
            {label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Input className="w-64" placeholder="Search title or company" value={q} onChange={(e) => setQ(e.target.value)} />
        {select(workType, setWorkType, [[ALL, "All types"], ["part_time", "Part time"], ["contract", "Contract"], ["casual", "Casual"], ["full_time", "Full time"]], "Type")}
        {view === "active" &&
          select(status, setStatus, [[ALL, "Any status"], ["new", "New"], ["saved", "Saved"], ["applied", "Applied"], ["hidden", "Hidden"]], "Status")}
        {select(source, setSource, [[ALL, "All sources"], ["seek", "SEEK"], ["jora", "Jora"]], "Source")}
        <span className="ml-auto text-sm text-muted-foreground">{isLoading ? "Loading…" : `${data.length} jobs`}</span>
      </div>
      <JobTable jobs={data} view={view} onSelect={setSelected} />
      <JobDrawer job={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
```

- [ ] **Step 4: Verify build and manual check**

Run: `cd frontend && npm run build`
Expected: build succeeds.
Manual: in one shell `cd backend && uv run seekhunter run --dry-run` (populates `backend/data`), then `cd backend && SEEKHUNTER_DEV=1 API_WRITE_TOKEN=dev-token uv run uvicorn seekhunter.api:create_app --factory --port 8090`; in another `cd frontend && npm run dev`, open the printed URL, confirm the jobs table renders, a drawer opens, status buttons work after setting token `dev-token`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: add jobs and excluded pages with detail drawer"
```

---

### Task 22: Searches page

**Files:**
- Modify: `frontend/src/pages/SearchesPage.tsx`

- [ ] **Step 1: Replace `frontend/src/pages/SearchesPage.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { type SearchProfile, WORK_TYPE_LABEL, type WorkType } from "@/lib/types";

const LOCATIONS = ["All Adelaide SA", "All Melbourne VIC", "All Sydney NSW", "All Perth WA", "All Brisbane QLD"];
const TYPES: WorkType[] = ["part_time", "contract", "casual", "full_time"];
const EMPTY: SearchProfile = { name: "", keywords: "", location: LOCATIONS[0], work_types: [], sources: ["seek", "jora"], enabled: true };

function toggle<T>(list: T[], v: T): T[] {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
}

function ProfileRow({ initial, onSaved }: { initial: SearchProfile; onSaved: () => void }) {
  const [p, setP] = useState(initial);
  const save = useMutation({
    mutationFn: () => (p.id ? api.updateProfile(p) : api.createProfile({ ...p, name: p.name || `${p.location} · ${p.keywords}` })),
    onSuccess: () => {
      toast.success("Saved");
      onSaved();
      if (!p.id) setP(EMPTY);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const remove = useMutation({ mutationFn: () => api.deleteProfile(p.id!), onSuccess: onSaved });
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-3 py-4">
        <Switch checked={p.enabled} onCheckedChange={(enabled) => setP({ ...p, enabled })} />
        <Input className="w-48" placeholder="keywords" value={p.keywords} onChange={(e) => setP({ ...p, keywords: e.target.value })} />
        <select className="h-9 rounded-md border px-2 text-sm" value={p.location} onChange={(e) => setP({ ...p, location: e.target.value })}>
          {LOCATIONS.map((l) => (
            <option key={l}>{l}</option>
          ))}
        </select>
        <div className="flex gap-1">
          {TYPES.map((t) => (
            <Button key={t} size="sm" variant={p.work_types.includes(t) ? "default" : "outline"} onClick={() => setP({ ...p, work_types: toggle(p.work_types, t) })}>
              {WORK_TYPE_LABEL[t]}
            </Button>
          ))}
        </div>
        <div className="flex gap-1">
          {(["seek", "jora"] as const).map((s) => (
            <Button key={s} size="sm" variant={p.sources.includes(s) ? "secondary" : "ghost"} onClick={() => setP({ ...p, sources: toggle(p.sources, s) })}>
              {s}
            </Button>
          ))}
        </div>
        <div className="ml-auto flex gap-2">
          <Button size="sm" onClick={() => save.mutate()} disabled={!p.keywords}>
            {p.id ? "Save" : "Add"}
          </Button>
          {p.id && (
            <Button size="sm" variant="ghost" onClick={() => remove.mutate()}>
              Delete
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export function SearchesPage() {
  const qc = useQueryClient();
  const { data = [] } = useQuery({ queryKey: ["profiles"], queryFn: api.profiles });
  const refresh = () => qc.invalidateQueries({ queryKey: ["profiles"] });
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">No work type selected = all types (full-time still ranked lower).</p>
      {data.map((p) => (
        <ProfileRow key={p.id} initial={p} onSaved={refresh} />
      ))}
      <h2 className="pt-4 font-medium">Add search</h2>
      <ProfileRow initial={EMPTY} onSaved={refresh} />
    </div>
  );
}
```

- [ ] **Step 2: Build**

Run: `cd frontend && npm run build`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/SearchesPage.tsx
git commit -m "feat: add search profiles page"
```

---

### Task 23: Settings and Runs pages

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`, `frontend/src/pages/RunsPage.tsx`

- [ ] **Step 1: Replace `frontend/src/pages/SettingsPage.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import type { AppSettings, Weights } from "@/lib/types";

type ListKey = {
  [K in keyof AppSettings]: AppSettings[K] extends string[] ? K : never;
}[keyof AppSettings];

const LISTS: [ListKey, string][] = [
  ["employer_allowlist", "Employer allowlist (overrides defence/bank)"],
  ["defence_employers", "Defence employers"],
  ["bank_employers", "Bank employers"],
  ["clearance_patterns", "Clearance patterns (regex)"],
  ["citizenship_patterns", "Citizenship/PR patterns (regex)"],
  ["defence_keywords", "Defence keywords (regex)"],
  ["bank_keywords", "Bank keywords (regex)"],
  ["role_boost_terms", "Role boost terms"],
  ["role_penalty_terms", "Role penalty terms"],
  ["llm_providers", "LLM provider order (anthropic, openclaw)"],
];
const WEIGHTS: [keyof Weights, string][] = [
  ["flexible_work", "Part-time/contract/casual points"],
  ["full_time", "Full-time points"],
  ["skill_max", "Skill match max"],
  ["role_max", "Role fit max"],
  ["skill_saturation", "Skills to reach max"],
];
const TOGGLES: [keyof AppSettings, string][] = [
  ["notify_enabled", "Telegram notifications"],
  ["recap_enabled", "Daily 21:15 recap"],
  ["llm_enabled", "AI scoring"],
  ["exclude_fintech", "Exclude fintech"],
];

export function SettingsPage() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [s, setS] = useState<AppSettings | null>(null);
  useEffect(() => setS(data ?? null), [data]);
  const fail = (e: Error) => toast.error(e.message.includes("401") ? "Set the write token first" : e.message);
  const save = useMutation({
    mutationFn: () => api.saveSettings(s!),
    onSuccess: () => {
      toast.success("Settings saved");
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: fail,
  });
  const run = useMutation({ mutationFn: api.triggerRun, onSuccess: () => toast.success("Run started"), onError: fail });
  const test = useMutation({ mutationFn: api.notifyTest, onSuccess: () => toast.success("Test sent"), onError: fail });
  if (!s) return <p>Loading…</p>;

  return (
    <div className="space-y-6">
      <div className="flex gap-2">
        <Button onClick={() => save.mutate()}>Save settings</Button>
        <Button variant="outline" onClick={() => run.mutate()}>
          Run now
        </Button>
        <Button variant="outline" onClick={() => test.mutate()}>
          Send test notification
        </Button>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Toggles & weights</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          {TOGGLES.map(([k, label]) => (
            <div key={k} className="flex items-center gap-2">
              <Switch checked={s[k] as boolean} onCheckedChange={(v) => setS({ ...s, [k]: v })} />
              <Label>{label}</Label>
            </div>
          ))}
          {WEIGHTS.map(([k, label]) => (
            <div key={k} className="space-y-1">
              <Label>{label}</Label>
              <Input type="number" value={s.weights[k]} onChange={(e) => setS({ ...s, weights: { ...s.weights, [k]: Number(e.target.value) } })} />
            </div>
          ))}
          <div className="space-y-1">
            <Label>Max notified per run</Label>
            <Input type="number" value={s.max_notify_per_run} onChange={(e) => setS({ ...s, max_notify_per_run: Number(e.target.value) })} />
          </div>
          <div className="space-y-1">
            <Label>Max pages per search</Label>
            <Input type="number" value={s.max_pages_per_search} onChange={(e) => setS({ ...s, max_pages_per_search: Number(e.target.value) })} />
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Lists (one per line)</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          {LISTS.map(([k, label]) => (
            <div key={k} className="space-y-1">
              <Label>{label}</Label>
              <Textarea
                rows={6}
                className="font-mono text-xs"
                value={s[k].join("\n")}
                onChange={(e) => setS({ ...s, [k]: e.target.value.split("\n").map((x) => x.trim()).filter(Boolean) })}
              />
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: Replace `frontend/src/pages/RunsPage.tsx`**

```tsx
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";

const fmt = (iso: string | null) =>
  iso ? new Date(iso.endsWith("Z") ? iso : `${iso}Z`).toLocaleString("en-AU", { timeZone: "Australia/Adelaide" }) : "—";

export function RunsPage() {
  const { data = [] } = useQuery({ queryKey: ["runs"], queryFn: api.runs, refetchInterval: 30_000 });
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Started</TableHead>
          <TableHead>Sources</TableHead>
          <TableHead>New</TableHead>
          <TableHead>Notified</TableHead>
          <TableHead>AI</TableHead>
          <TableHead>Error</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.map((r) => (
          <TableRow key={r.id}>
            <TableCell>{fmt(r.started_at)}</TableCell>
            <TableCell className="space-x-1">
              {Object.entries(r.source_status).map(([name, st]) => (
                <Badge key={name} variant={st.status === "ok" ? "secondary" : "destructive"} title={st.error ?? ""}>
                  {name} {st.new}/{st.found} · {st.requests} req{st.blocked ? ` · ${st.blocked}×403` : ""}
                </Badge>
              ))}
            </TableCell>
            <TableCell>{r.new_jobs}</TableCell>
            <TableCell>{r.notified}</TableCell>
            <TableCell>{r.llm_provider ?? "rules"}</TableCell>
            <TableCell className="max-w-xs truncate text-sm text-destructive">{r.error}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
```

- [ ] **Step 3: Build, test, lint**

Run: `cd frontend && npm test && npm run build && npm run lint`
Expected: all succeed (fix lint warnings the template's ESLint flags, e.g. unused imports).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages
git commit -m "feat: add settings and runs pages"
```

---

### Task 24: Deploy assets (systemd, bootstrap, deploy script)

**Files:**
- Create: `deploy/systemd/seekhunter-web.service`, `deploy/systemd/seekhunter-crawl.service`, `deploy/systemd/seekhunter-crawl.timer`, `deploy/systemd/seekhunter-recap.service`, `deploy/systemd/seekhunter-recap.timer`, `deploy/systemd/seekhunter-rescore.service`, `deploy/env.example`, `deploy/bootstrap-vps.sh`, `deploy/deploy.sh`

- [ ] **Step 1: `deploy/systemd/seekhunter-web.service`**

```ini
[Unit]
Description=SeekHunter web/API
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/opt/seek-hunter/app/backend
EnvironmentFile=/opt/seek-hunter/.env
Environment=PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/root/.local/bin/uv run --frozen --no-dev uvicorn seekhunter.api:create_app --factory --host 0.0.0.0 --port 8090
Restart=always
RestartSec=5
MemoryMax=400M

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: `deploy/systemd/seekhunter-crawl.service`**

```ini
[Unit]
Description=SeekHunter crawl run
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/opt/seek-hunter/app/backend
EnvironmentFile=/opt/seek-hunter/.env
Environment=PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/root/.local/bin/uv run --frozen --no-dev seekhunter run
SuccessExitStatus=75
TimeoutStartSec=45min
MemoryMax=600M
```

- [ ] **Step 3: `deploy/systemd/seekhunter-crawl.timer`**

```ini
[Unit]
Description=SeekHunter crawl every 2h 07:00-21:00 Adelaide

[Timer]
OnCalendar=*-*-* 07,09,11,13,15,17,19,21:00:00 Australia/Adelaide
RandomizedDelaySec=5min
Persistent=false

[Install]
WantedBy=timers.target
```

- [ ] **Step 4: `deploy/systemd/seekhunter-recap.service` and `.timer`**

```ini
[Unit]
Description=SeekHunter daily recap

[Service]
Type=oneshot
WorkingDirectory=/opt/seek-hunter/app/backend
EnvironmentFile=/opt/seek-hunter/.env
Environment=PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/root/.local/bin/uv run --frozen --no-dev seekhunter recap
SuccessExitStatus=75
```

```ini
[Unit]
Description=SeekHunter recap 21:15 Adelaide

[Timer]
OnCalendar=*-*-* 21:15:00 Australia/Adelaide

[Install]
WantedBy=timers.target
```

- [ ] **Step 4b: `deploy/systemd/seekhunter-rescore.service`** (started by book-cv's deploy, no timer)

```ini
[Unit]
Description=SeekHunter rescore after resume change

[Service]
Type=oneshot
WorkingDirectory=/opt/seek-hunter/app/backend
EnvironmentFile=/opt/seek-hunter/.env
Environment=PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/root/.local/bin/uv run --frozen --no-dev seekhunter rescore
TimeoutStartSec=50min
```

- [ ] **Step 5: `deploy/env.example`**

```
DATABASE_URL=sqlite:////opt/seek-hunter/data/seekhunter.db
DATA_DIR=/opt/seek-hunter/data
RESUME_DIR=/opt/seek-hunter/book-cv/sections/resume
STATIC_DIR=/opt/seek-hunter/app/frontend/dist
PUBLIC_URL=https://seekhunter.bookmountain.work
TELEGRAM_TARGET=1635495359
OPENCLAW_BIN=/usr/bin/openclaw
ALLOWED_CIDRS=127.0.0.1/32,192.168.4.0/24,100.64.0.0/10
ALLOWED_PUBLIC_IPS=180.150.112.113
TUNNEL_PROXY_IPS=192.168.4.106
API_WRITE_TOKEN=change-me
ANTHROPIC_API_KEY=
```

- [ ] **Step 6: `deploy/bootstrap-vps.sh`** (one-time, run as root on .50)

```bash
#!/usr/bin/env bash
set -euo pipefail
command -v rsync >/dev/null || apt-get install -y rsync
if [ ! -x /root/.local/bin/uv ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
/root/.local/bin/uv python install 3.12
mkdir -p /opt/seek-hunter/{app,data,book-cv}
if [ ! -f /opt/seek-hunter/.env ]; then
  sed "s/^API_WRITE_TOKEN=.*/API_WRITE_TOKEN=$(openssl rand -hex 24)/" /tmp/seekhunter-env.example > /opt/seek-hunter/.env
  chmod 600 /opt/seek-hunter/.env
  echo "Created /opt/seek-hunter/.env (add ANTHROPIC_API_KEY)"
fi
echo "bootstrap done"
```

- [ ] **Step 7: `deploy/deploy.sh`** (runs on .50, called by CI after rsync)

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /opt/seek-hunter/app/backend
/root/.local/bin/uv sync --frozen --no-dev
install -m 644 /opt/seek-hunter/app/deploy/systemd/*.service /opt/seek-hunter/app/deploy/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now seekhunter-crawl.timer seekhunter-recap.timer
systemctl enable seekhunter-web.service
systemctl restart seekhunter-web.service
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8090/api/health >/dev/null; then echo "healthy"; exit 0; fi
  sleep 1
done
journalctl -u seekhunter-web -n 80 --no-pager
exit 1
```

- [ ] **Step 8: Make scripts executable and commit**

```bash
chmod +x deploy/*.sh
git add deploy
git commit -m "chore: add systemd units and VPS deploy scripts"
```

---

### Task 24b: OpenClaw skill + API wrapper

OpenClaw already owns the Telegram bot and reads Book's replies. This skill teaches its agent to drive SeekHunter, so Book can say "save #142", "why #142?", "only contract roles", "add Melbourne react searches", or "anything new?" in Telegram.

**Files:**
- Create: `deploy/bin/seekhunter-api`, `openclaw-skill/seekhunter/SKILL.md`
- Modify: `deploy/deploy.sh`

- [ ] **Step 1: Create `deploy/bin/seekhunter-api`** (installed to `/usr/local/bin` on .50)

```bash
#!/usr/bin/env bash
# Usage: seekhunter-api METHOD PATH [JSON_BODY]
#   seekhunter-api GET /api/summary?hours=24
#   seekhunter-api PATCH /api/jobs/142 '{"status":"saved"}'
set -euo pipefail
METHOD="${1:?method}"; PATH_="${2:?path}"; BODY="${3:-}"
TOKEN="$(grep -E '^API_WRITE_TOKEN=' /opt/seek-hunter/.env | cut -d= -f2-)"
ARGS=(-sS -X "$METHOD" "http://127.0.0.1:8090${PATH_}" -w '\n[HTTP %{http_code}]\n')
if [ "$METHOD" != "GET" ]; then ARGS+=(-H "Authorization: Bearer ${TOKEN}"); fi
if [ -n "$BODY" ]; then ARGS+=(-H "Content-Type: application/json" -d "$BODY"); fi
exec curl "${ARGS[@]}"
```

- [ ] **Step 2: Create `openclaw-skill/seekhunter/SKILL.md`**

````markdown
---
name: seekhunter
description: "Book's job-hunt tracker (SeekHunter). Use when Book mentions jobs, a job #id from a SeekHunter digest, saving/hiding/applying, why a job fits, job searches/filters, or asks what's new on SEEK/Jora."
metadata:
  {
    "openclaw":
      {
        "emoji": "🎯",
        "requires": { "bins": ["seekhunter-api"] },
      },
  }
---

# SeekHunter

SeekHunter crawls SEEK and Jora every 2 hours (07:00–21:00 Adelaide). It drops jobs needing security clearance, citizenship/PR, defence, or banks, scores the rest against Book's resume (part-time/contract/casual first because of his student visa), and posts digests to this Telegram chat. Each digest line starts with a job id like `#142`.

All access goes through the `seekhunter-api METHOD PATH [JSON]` command (localhost API; auth is handled). Never invent job data; read it from the API. Keep replies short.

## Read
- What's new: `seekhunter-api GET "/api/summary?hours=24"` (plain text, one job per line)
- One job in detail (fit, matched/missing skills, AI note, description): `seekhunter-api GET /api/jobs/142/brief`
- List as JSON: `seekhunter-api GET "/api/jobs?view=active&status=saved"` (`view=excluded` for excluded; filters: `work_type=part_time|contract|casual|full_time`, `source=seek|jora`, `q=text`)
- Searches: `seekhunter-api GET /api/search-profiles`
- Settings: `seekhunter-api GET /api/settings`
- Recent runs/health: `seekhunter-api GET /api/runs`

## Act
- Status: `seekhunter-api PATCH /api/jobs/142 '{"status":"saved"}'` (`saved|applied|hidden|new`); notes: `'{"notes":"..."}'`
- Wrongly excluded job: `seekhunter-api POST /api/jobs/142/unexclude '{"allowlist_employer":false}'`
- Add a search: `seekhunter-api POST /api/search-profiles '{"name":"Melbourne · react","keywords":"react","location":"All Melbourne VIC","work_types":[],"sources":["seek","jora"],"enabled":true}'` (locations: "All Adelaide SA", "All Melbourne VIC", "All Sydney NSW", "All Perth WA"; work_types empty = all)
- Change a search: GET it from the list, then `PUT /api/search-profiles/{id}` with the full object
- Settings (blocklists, weights, toggles): GET `/api/settings`, modify the field, then `PUT /api/settings` with the **full** JSON (never send a partial object)
- Run a crawl now: `seekhunter-api POST /api/runs`

## How to answer
- "why #142?" / "am I a fit?": read the brief, then explain the overlap and the gaps in 3–5 lines. Mention visa fit (hours flag) when relevant.
- Before destructive changes (deleting searches, editing blocklists), restate the change in one line and do it. If ambiguous, ask.
- When Book states a lasting preference ("no recruiter X", "only contract"), apply it via settings/searches and remember it.
- Don't touch other cron jobs or channels.
````

- [ ] **Step 3: Install wrapper and skill in `deploy/deploy.sh`**

Insert after the `uv sync` line:
```bash
install -m 755 /opt/seek-hunter/app/deploy/bin/seekhunter-api /usr/local/bin/seekhunter-api
openclaw skills install /opt/seek-hunter/app/openclaw-skill/seekhunter --as seekhunter --force \
  --acknowledge-install-policy-warning || echo "WARN: openclaw skill install failed"
```

- [ ] **Step 4: Commit**

```bash
chmod +x deploy/bin/seekhunter-api
git add deploy openclaw-skill
git commit -m "feat: add OpenClaw skill and API wrapper for Telegram control"
```

---

### Task 25: GitHub Actions CI/CD

**Files:**
- Create: `.github/workflows/ci-deploy.yml`

- [ ] **Step 1: Create the workflow**

```yaml
name: CI and deploy

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: seek-hunter-main
  cancel-in-progress: false

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - name: Backend lint and tests
        working-directory: backend
        run: |
          uv sync --frozen
          uv run ruff check .
          uv run pytest -q
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - name: Frontend tests and build
        working-directory: frontend
        run: |
          npm ci
          npm test
          npm run build
      - uses: actions/upload-artifact@v4
        with:
          name: frontend-dist
          path: frontend/dist
          retention-days: 3

  deploy:
    needs: verify
    if: github.event_name != 'pull_request' && github.ref == 'refs/heads/main'
    runs-on: [self-hosted, linux, x64, seek-hunter]
    timeout-minutes: 20
    environment:
      name: production
      url: https://seekhunter.bookmountain.work
    env:
      TARGET: root@192.168.4.50
      SSH_OPTS: -i /home/book/.ssh/seekhunter_deploy -o StrictHostKeyChecking=accept-new
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: actions/download-artifact@v4
        with:
          name: frontend-dist
          path: frontend/dist
      - name: Sync app  # resume sections arrive via book-cv's own deploy (Task 26 Step 9b)
        run: |
          rsync -az --delete -e "ssh $SSH_OPTS" \
            --exclude '.git/' --exclude '.github/' --exclude 'backend/.venv/' --exclude 'backend/data/' \
            --exclude 'frontend/node_modules/' --exclude '.env' \
            ./ "$TARGET:/opt/seek-hunter/app/"
      - name: Install and restart
        run: ssh $SSH_OPTS "$TARGET" 'bash /opt/seek-hunter/app/deploy/deploy.sh'
      - name: Health check from runner
        run: curl -fsS http://192.168.4.50:8090/api/health
```

- [ ] **Step 2: Make sure lockfiles are committed**

Run: `git status --short backend/uv.lock frontend/package-lock.json`
Expected: both tracked (commit them if they show as untracked).

- [ ] **Step 3: Commit (don't push yet; infra comes first)**

```bash
git add .github/workflows/ci-deploy.yml backend/uv.lock frontend/package-lock.json
git commit -m "ci: add verify and self-hosted deploy workflow"
```

---

### Task 26: One-time infrastructure and first deploy

These steps run remote commands. Credentials: `sshpass -p 'Book1995*'` for `root@192.168.4.50` and `book@192.168.4.106` (sudo on .106 with the same password via `sudo -S`). Do **not** change passwords or sshd config.

- [ ] **Step 1: Bootstrap `.50`**

```bash
sshpass -p 'Book1995*' scp deploy/env.example root@192.168.4.50:/tmp/seekhunter-env.example
sshpass -p 'Book1995*' scp deploy/bootstrap-vps.sh root@192.168.4.50:/tmp/bootstrap-vps.sh
sshpass -p 'Book1995*' ssh root@192.168.4.50 'bash /tmp/bootstrap-vps.sh && /root/.local/bin/uv --version && df -h / | tail -1'
```
Expected: "bootstrap done", uv version printed, free disk still > 3 GB.

- [ ] **Step 2: Put the Anthropic key in `.env`**

Ask Book for the Anthropic API key (Console → API keys). Then:
```bash
sshpass -p 'Book1995*' ssh root@192.168.4.50 "sed -i 's|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=<key>|' /opt/seek-hunter/.env"
```
Never echo or commit the key. Read back the generated write token for Book with `grep API_WRITE_TOKEN /opt/seek-hunter/.env`.

- [ ] **Step 2b: Create the tool-less OpenClaw scoring agent**

Codex fallback scoring sends untrusted job-ad text to OpenClaw, so it must go to a dedicated agent with no tools, never `main`.
```bash
sshpass -p 'Book1995*' ssh root@192.168.4.50 '
set -e
mkdir -p /opt/seek-hunter/openclaw-scorer
openclaw agents list | grep -q seekhunter-scorer || openclaw agents add seekhunter-scorer --non-interactive --workspace /opt/seek-hunter/openclaw-scorer
openclaw config patch "{agents:{entries:{\"seekhunter-scorer\":{tools:{profile:\"minimal\",deny:[\"exec\",\"bash\",\"process\",\"read\",\"write\",\"edit\",\"apply_patch\",\"web_search\",\"web_fetch\",\"browser\",\"message\",\"cron\",\"sessions_spawn\",\"sessions_send\",\"gateway\",\"nodes\",\"canvas\"]}}}}}"
openclaw agent --agent seekhunter-scorer --session-id scorer-check --thinking low --json -m "Reply with exactly: {\"ok\": true}" 2>/dev/null > /tmp/scorer.json
python3 -c "import json; d=json.load(open(\"/tmp/scorer.json\")); m=d[\"result\"][\"meta\"]; print(m[\"finalAssistantVisibleText\"]); print(json.dumps(m)[:20000].count(\"\\\"name\\\"\"), \"tool entries\")"
grep -o "\"name\": \"[a-z_]*\"" /tmp/scorer.json | sort -u
rm /tmp/scorer.json
'
```
Expected: reply `{"ok": true}`, and the listed tool names contain no exec/read/write/web/message tools. If any remain, add them to the `deny` list and re-check. Also confirm `openclaw agents list` shows that `main` is unchanged. If `openclaw agents add` needs extra auth for the new agent (model login), run `openclaw agents add` interactively with Book, or set `--model openai/gpt-5.5` to reuse the existing OpenAI OAuth profile.

- [ ] **Step 2c: Check Telegram formatting**

`openclaw message send` may parse Markdown. Send `seekhunter-api`-independent test text with special characters:
```bash
sshpass -p 'Book1995*' ssh root@192.168.4.50 'openclaw message send --channel telegram --target 1635495359 --message "🎯 format test: C#/.NET_Core *Urgent* <Senior> a_b_c https://x.com/a_b?c=1&d=2"'
```
Ask Book whether it arrived verbatim. If characters were eaten or the send failed, add escaping of `* _ [ ] < > &` for titles, companies and AI notes in `notify._format_item` (one commit, plus a test), before enabling the timers.

- [ ] **Step 3: Deploy key from vm100 runner user to `.50`**

```bash
sshpass -p 'Book1995*' ssh book@192.168.4.106 'test -f ~/.ssh/seekhunter_deploy || ssh-keygen -t ed25519 -N "" -C seekhunter-deploy -f ~/.ssh/seekhunter_deploy; cat ~/.ssh/seekhunter_deploy.pub' > /tmp/sh_pub
sshpass -p 'Book1995*' ssh root@192.168.4.50 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && grep -qF '$(cat /tmp/sh_pub)' ~/.ssh/authorized_keys 2>/dev/null || echo '$(cat /tmp/sh_pub)' >> ~/.ssh/authorized_keys"
sshpass -p 'Book1995*' ssh book@192.168.4.106 'ssh -i ~/.ssh/seekhunter_deploy -o StrictHostKeyChecking=accept-new root@192.168.4.50 echo key-ok'
rm /tmp/sh_pub
```
Expected: `key-ok`.

- [ ] **Step 4: Register the self-hosted runner on vm100**

Ask Book for a registration token: GitHub → `bookmountain/seek-hunter` → Settings → Actions → Runners → New self-hosted runner (Linux x64) → copy the `--token` value. Then:
```bash
sshpass -p 'Book1995*' ssh book@192.168.4.106 '
set -e
VER=$(curl -s https://api.github.com/repos/actions/runner/releases/latest | python3 -c "import sys, json; print(json.load(sys.stdin)[\"tag_name\"].lstrip(\"v\"))")
echo "Book1995*" | sudo -S mkdir -p /actions-runner-seek-hunter && echo "Book1995*" | sudo -S chown book:book /actions-runner-seek-hunter
cd /actions-runner-seek-hunter
curl -sL -o runner.tgz https://github.com/actions/runner/releases/download/v${VER}/actions-runner-linux-x64-${VER}.tar.gz
tar xzf runner.tgz && rm runner.tgz
./config.sh --unattended --url https://github.com/bookmountain/seek-hunter --token <TOKEN> --name vm100-seek-hunter --labels seek-hunter --work _work
echo "Book1995*" | sudo -S ./svc.sh install book
echo "Book1995*" | sudo -S ./svc.sh start
'
```
Expected: runner service `actions.runner.bookmountain-seek-hunter.vm100-seek-hunter.service` active; it shows "Idle" in GitHub settings.

- [ ] **Step 5: Cloudflare tunnel ingress + DNS on vm100**

```bash
sshpass -p 'Book1995*' ssh book@192.168.4.106 '
set -e
CFG=/etc/cloudflared/config.yml
echo "Book1995*" | sudo -S cp $CFG $CFG.bak.$(date +%Y%m%d%H%M%S)
grep -q seekhunter.bookmountain.work $CFG || echo "Book1995*" | sudo -S sed -i \
  "s#^  - service: http_status:404#  - hostname: seekhunter.bookmountain.work\n    service: http://192.168.4.50:8090\n  - service: http_status:404#" $CFG
grep -A1 seekhunter $CFG
cloudflared tunnel route dns 07c09f06-eb9e-4ff1-af6f-e67de11a37f9 seekhunter.bookmountain.work || true
echo "Book1995*" | sudo -S cloudflared --config $CFG tunnel ingress validate
echo "Book1995*" | sudo -S systemctl restart cloudflared
systemctl is-active cloudflared
'
```
Expected: "Validating rules... OK", `active`. The DNS route prints "Added CNAME" (or "already exists").

- [ ] **Step 6: Push and watch the first deploy**

```bash
git push origin main
```
Then watch GitHub Actions (or ask Book to): `verify` passes on ubuntu-latest, `deploy` runs on `vm100-seek-hunter` and ends with a healthy check.

- [ ] **Step 7: First live run on `.50` (dry-run, then real)**

```bash
sshpass -p 'Book1995*' ssh root@192.168.4.50 'cd /opt/seek-hunter/app/backend && set -a && . /opt/seek-hunter/.env && set +a && /root/.local/bin/uv run --frozen --no-dev seekhunter run --dry-run | tail -40'
```
Expected: dry-run digest printed, JSON report with `seek` ok and `jora` ok/degraded, `llm_provider` = `anthropic`. Because dry-run doesn't mark notifications, the next real run sends them:
```bash
sshpass -p 'Book1995*' ssh root@192.168.4.50 'systemctl start seekhunter-crawl.service; journalctl -u seekhunter-crawl -n 30 --no-pager; systemctl list-timers | grep seekhunter'
```
Expected: Telegram receives "🎯 SeekHunter · N new" (top 20, "+N more"); timers list next runs at the next odd hour and 21:15.

- [ ] **Step 8: Verify access control**

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://seekhunter.bookmountain.work/api/jobs   # from home: 200
curl -s -o /dev/null -w "%{http_code}\n" https://seekhunter.bookmountain.work/api/health # 200
```
And ask Book to open `https://seekhunter.bookmountain.work` on phone mobile data (not home IP, no Tailscale exit node): it should return `{"detail":"forbidden"}`.

- [ ] **Step 9: Confirm OpenClaw is unaffected**

```bash
sshpass -p 'Book1995*' ssh root@192.168.4.50 'openclaw cron list 2>/dev/null | grep -i "Noon Adelaide"'
```
Expected: the noon job is still listed with its schedule unchanged.

- [ ] **Step 9b: Make book-cv resume changes flow to SeekHunter**

In `/Users/book/Documents/code/book-cv/.github/workflows/deploy.yml`, append this step to the end of the `deploy` job's `steps` (after "Restart containers"):
```yaml
      - name: Sync resume to SeekHunter
        continue-on-error: true
        run: |
          rsync -az --delete -e "ssh -i /home/book/.ssh/seekhunter_deploy -o StrictHostKeyChecking=accept-new" \
            latex/sections/ root@192.168.4.50:/opt/seek-hunter/book-cv/sections/
          ssh -i /home/book/.ssh/seekhunter_deploy root@192.168.4.50 'systemctl start --no-block seekhunter-rescore.service'
```
Check the runner user first: `systemctl show -p User actions.runner.bookmountain-book-cv.vm100.service` must print `User=book` (so `/home/book/.ssh/seekhunter_deploy` is readable). Commit in the book-cv repo (`git -C ../book-cv add .github/workflows/deploy.yml && git -C ../book-cv commit -m "ci: sync resume sections to SeekHunter"`). **Ask Book before pushing**, because a push to `master` also redeploys the website. After the push, verify on `.50`: `journalctl -u seekhunter-rescore -n 5 --no-pager` shows "rescored N jobs".

- [ ] **Step 9c: Verify the OpenClaw skill end to end**

```bash
sshpass -p 'Book1995*' ssh root@192.168.4.50 'openclaw skills info seekhunter; seekhunter-api GET "/api/summary?hours=48" | head'
```
Expected: the skill shows as ready (its `seekhunter-api` requirement is satisfied) and the summary lists jobs. Then ask Book to send OpenClaw in Telegram: "anything new on SeekHunter?" and "why #<id>?" for an id from the digest, and to try "save #<id>". Confirm the status changed in the web UI.

- [ ] **Step 10: Update TODO and commit**

In `TODO.md` change `- [ ] **A — Core**` to `- [x] **A — Core**`, then:
```bash
git add TODO.md
git commit -m "docs: mark core sub-project as deployed"
git push origin main
```

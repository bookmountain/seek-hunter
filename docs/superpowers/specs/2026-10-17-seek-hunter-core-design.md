# SeekHunter — Core (Sub-project A) Design

**Date:** 2026-10-17
**Status:** Approved in brainstorming, pending spec review
**Repo:** `github.com/bookmountain/seek-hunter`
**Public URL:** `https://seekhunter.bookmountain.work`

## 1. Goal

Find new IT/software job listings on SEEK and Jora as early as possible, drop ones Book cannot take (security clearance, citizenship/PR, defence, banks), rank the rest by fit with Book's resume and visa situation, and notify via Telegram through the existing OpenClaw bot. A web UI lets Book browse, triage, and adjust filters.

Out of scope for A (see §11 TODO): resume/cover-letter tailoring (B), market insights dashboard (C).

## 2. Context and constraints

- **User:** Full-stack engineer, ~5 yrs (ex-Microsoft), Master of IT at Adelaide University until July 2027, on a student visa (48 h/fortnight cap during semester).
- **Resume source:** `../book-cv/latex/sections/resume/` (modular LaTeX: `skills.tex`, `summary.tex`, `experience/*.tex`).
- **App host:** `root@192.168.4.50` (Proxmox LXC "CT101"): Ubuntu 22.04, 2 vCPU, 4 GB RAM, ~4 GB free disk, Node 24, system Python 3.10 without pip/venv, no Docker. Runs OpenClaw 2026.10.4 (gateway on loopback :18789, Telegram channel, owner chat `1635495359`).
- **Existing OpenClaw cron** "Noon Adelaide IT jobs" (12:00 Australia/Adelaide) is left untouched. Its 403s come from fetching SEEK job HTML pages.
- **Tunnel/runner host:** `book@192.168.4.106` (vm100): cloudflared tunnel `07c09f06-…` with `/etc/cloudflared/config.yml`; one self-hosted GitHub Actions runner per repo.
- **AI budget:** $100/month Anthropic API credit (Max 5x perk). AI must be optional; the system must work fully without it.

### Verified source access (from 192.168.4.50 / LAN, 2026-10-17)

| Endpoint | Result |
|---|---|
| SEEK `GET https://www.seek.com.au/api/jobsearch/v5/search` (plain HTTP client) | 200 JSON |
| SEEK `POST https://www.seek.com.au/graphql` `jobDetails` (full HTML description) | 200 |
| SEEK job HTML page `/job/{id}` | 403 (not used) |
| Jora `https://au.jora.com/j?q=…&l=…` plain curl | 403 |
| Jora with `curl_cffi` `impersonate="chrome"` | 200, ~30 job cards/page |

## 3. Stack

- **Backend:** Python 3.12 (managed by `uv`, isolated from system Python), FastAPI, SQLModel + SQLite (tables created with `create_all`; Alembic deferred until a column migration is needed), `curl_cffi`, `selectolax` (HTML parsing), `anthropic` SDK. Scheduling via systemd timers (no in-process scheduler).
- **Frontend:** React + Vite + TypeScript, React Router, TanStack Query, Tailwind + shadcn/ui. Built to static files and served by FastAPI. No Node process at runtime.
- **Tests:** pytest, ruff; Vitest for frontend.

## 4. Architecture

```
seek-hunter/
├── backend/
│   ├── pyproject.toml / uv.lock
│   ├── alembic/
│   ├── seekhunter/
│   │   ├── config.py          env + settings loading
│   │   ├── db.py, models.py   SQLModel tables (§6)
│   │   ├── sources/
│   │   │   ├── base.py        Source protocol: search(profile) -> [JobStub]; details(stub) -> JobDetail
│   │   │   ├── seek.py        JSON search + GraphQL jobDetails
│   │   │   └── jora.py        curl_cffi + selectolax; details from Jora job page
│   │   ├── http.py            shared polite client (delays, backoff, impersonation)
│   │   ├── profile.py         parse book-cv LaTeX -> Profile(skills, aliases, titles, summary)
│   │   ├── filters.py         hard exclusions (§5.1)
│   │   ├── scoring.py         rule score + LLM blend (§5.2)
│   │   ├── llm/
│   │   │   ├── base.py        LLMProvider protocol: score(profile, job) -> LLMScore | raises Unavailable
│   │   │   ├── anthropic_provider.py   Claude Haiku 4.5 (claude-haiku-4-5)
│   │   │   ├── openclaw_provider.py    `openclaw agent` CLI (Codex via OpenAI OAuth) fallback
│   │   │   └── chain.py       tries providers in configured order; None if all unavailable
│   │   ├── notify.py          format + `openclaw message send`; outbox retry
│   │   ├── pipeline.py        run orchestration (§7)
│   │   ├── security.py        IP allowlist middleware + write-token check
│   │   └── api.py             REST API + static file serving
│   ├── cli.py                 `seekhunter run [--dry-run]`, `seekhunter recap`, `seekhunter notify-test`
│   └── tests/ (fixtures/: saved SEEK JSON, GraphQL, Jora HTML)
├── frontend/                  Vite React app
├── deploy/
│   ├── systemd/ seekhunter-web.service, seekhunter-crawl.{service,timer}, seekhunter-recap.{service,timer}
│   ├── bootstrap-vps.sh       one-time: uv, Python 3.12, dirs, units
│   └── deploy.sh              invoked by CI over SSH
└── .github/workflows/ci-deploy.yml
```

Each unit has one job and a narrow interface: sources know nothing about scoring; filters/scoring are pure functions of `(Profile, Settings, JobDetail)`; providers are swappable behind `LLMProvider`; the pipeline is the only orchestrator.

## 5. Filtering and scoring

### 5.1 Hard exclusions

A job is excluded (stored with reason codes, never notified) if any rule matches. Matching is case-insensitive over title + company + full description.

| Code | Rule |
|---|---|
| `clearance` | `NV1`, `NV2`, `negative vetting`, `baseline (security )?clearance`, `AGSVA`, `PV clearance`, "(obtain\|hold\|maintain) … (security )?clearance" |
| `citizenship` | "Australian citizen(ship)? (is )?(required\|only)", "must be an Australian citizen", "permanent residen(t\|cy) (required\|only)", "PR required", "citizens or permanent residents only" |
| `defence` | employer blocklist (BAE Systems, Saab, Lockheed Martin, Raytheon, Boeing Defence, ASC, Naval Group, Thales, Leidos, Babcock, Northrop Grumman, Kongsberg, DSTG, Department of Defence, Nova Systems, …) or keywords ("defence industry", "defence prime", "Defence program", "Department of Defence") |
| `bank` | employer blocklist (Commonwealth Bank/CBA, NAB, ANZ, Westpac, BankSA, St.George, Bank of Melbourne, Macquarie, Bendigo, BOQ, ING, …) or recruiter phrasing ("leading bank", "big four bank", "major bank") |

**Negations:** each regex hit is checked against a ±40-char window for negations ("no clearance required", "not required", "clearance is not"); a negated hit does not exclude.

All lists, regexes, and an employer **allowlist** (overrides blocklists) live in `settings` and are editable in the UI. Optional toggle `exclude_fintech` (default off).

### 5.2 Score (0–100, used only for ordering; no notification threshold)

| Component | Max | Logic |
|---|---|---|
| Work type | 35 | Casual / Part-time / Contract-Temp = 35; Full-time = 10 (adjustable) |
| Skill match | 50 | Matched profile skills (with aliases: TS↔TypeScript, .NET↔C#, Postgres↔PostgreSQL, Next↔Next.js, …), weighted by skill section; saturates at ~8 strong matches |
| Role fit | 15 | Boost: software/full-stack/frontend/backend/AI engineer/graduate developer titles. Penalty: Principal, Head of, Director, "10+ years", helpdesk/network/desktop support |

**LLM blend (optional):** if a provider returns a score, `final = 0.6 × rule + 0.4 × llm`, and its one-line `why` is stored and shown. Otherwise `final = rule`.

**Visa flag (not exclusion):** stated minimum ≥ 24 h/week, or "full-time hours" on a non-full-time listing, gets `⚠️ hours` tag.

**Freshness:** searches request listings ≤ 7 days old (SEEK `daterange=7`; Jora date filter / parse posted date and drop > 7 days). There is no freshness score.

## 6. Data model (SQLite at `/opt/seek-hunter/data/seekhunter.db`)

- `jobs`: id, source (`seek`|`jora`), external_id (unique with source), title, company, location, work_type, salary_label, listed_at, url, description_html, description_text, dedupe_key (normalized title+company), canonical_job_id (nullable; set when a Jora listing duplicates a SEEK one), first_seen_at.
- `job_evaluations`: job_id, excluded (bool), exclusion_reasons (JSON), rule_score, llm_score, llm_note, llm_provider, final_score, matched_skills (JSON), flags (JSON), created_at. One row per job (overwritten on re-evaluation).
- `jobs` also carries status (`new`|`saved`|`applied`|`hidden`), notes, force_include (manual un-exclude), notified_at.
- `search_profiles`: id, name, keywords, location, work_types (JSON), sources (JSON), enabled.
  Defaults (location "All Adelaide SA"): "software engineer", "developer", "full stack", "frontend", "AI engineer", "graduate developer".
- `settings`: single JSON document (blocklists, allowlist, regexes, weights, schedule display, LLM provider order, notify on/off, recap on/off).
- `runs`: id, started_at, finished_at, source_status (JSON: ok/degraded, request count, 403/429 count), new_jobs, notified (bool), error.
- `outbox`: id, payload, attempts, last_error, sent_at.

## 7. Run pipeline (`seekhunter run`)

1. Load profile (from synced `book-cv` sections) and settings.
2. For each enabled search profile × source: `search()` all pages within 7 days.
3. Upsert stubs; anything with an unseen (source, external_id) is **new**.
4. Fetch details only for new jobs.
5. Dedupe: if a new Jora job's `dedupe_key` matches an existing SEEK job, link it via `canonical_job_id` and don't notify it separately.
6. Filter → score → LLM blend (only for non-excluded new jobs) → store evaluation.
7. Notification candidates = active jobs (not excluded or force_include, not duplicates, not hidden) with `notified_at IS NULL` first seen within 48 h. Send the top 20 by score; mark all candidates notified; append "+N more" if truncated. On send failure, write to `outbox`.
8. Record the run. If every source has failed for 3 consecutive runs, send a one-line ⚠️ health alert (at most once per 24 h).

**Politeness/anti-block (`http.py`):** one `curl_cffi` session per source with `impersonate="chrome"`, random 2–5 s delay between requests, max ~3 search pages per profile, exponential backoff (30 s, 90 s) on 403/429, then mark the source `degraded` for this run and continue with the others. The digest notes "Jora unavailable this run" when relevant.

**Schedule (systemd timers, `Australia/Adelaide`):**
- Crawl: every 2 h from 07:00 to 21:00 (07, 09, 11, 13, 15, 17, 19, 21), `RandomizedDelaySec=5min`. Messages are sent only when there are new jobs.
- Recap: 21:15 daily (toggle in settings): today's new jobs sorted by score, plus the excluded count.
- The 12:00 OpenClaw job is unaffected (no 12:00 run, separate 🎯 header).

## 8. Notifications

Sent via `openclaw message send --channel telegram --target 1635495359 --message <text>` executed locally on `.50`. This uses OpenClaw's bot as a sender only, without reading updates, so it doesn't conflict with OpenClaw.

```
🎯 SeekHunter · 3 new (13:00)
1. [82] Full Stack Developer — Acme · Adelaide · Contract 💼
   React, TypeScript, Node ✓ · "Strong match on React/Next + Azure"
   https://www.seek.com.au/job/123
2. …
→ https://seekhunter.bookmountain.work
```

Up to 10 jobs per message; overflow is split into multiple messages. 💼 = casual/part-time/contract; ⚠️ = hours flag.

## 9. Web UI and API

**Pages:**
1. **Jobs:** table with filter chips (work type, location, source, status), score badge, new-since-last-visit marker. The detail drawer shows the description with matched skills highlighted, the LLM note, links to SEEK/Jora, and Save / Applied / Hide / Notes.
2. **Excluded:** same table plus reason codes and the matching snippet; "Un-exclude" and "Allowlist employer".
3. **Searches:** CRUD for search profiles (keywords, location such as Adelaide / Melbourne / Sydney / Perth, work types, sources).
4. **Settings:** blocklists, allowlist, regexes, weights, LLM provider order, notify/recap toggles, "Send test notification", "Run now".
5. **Runs:** run history and per-source health.

**API (prefix `/api`):** `GET /health`, `GET /jobs`, `GET /jobs/{id}`, `PATCH /jobs/{id}/status`, `POST /jobs/{id}/unexclude`, `GET|POST|PUT|DELETE /search-profiles`, `GET|PUT /settings`, `GET /runs`, `POST /runs` (trigger), `POST /notify/test`.

**Access control (`security.py`):**
- IP allowlist middleware. Allowed: client IP within `ALLOWED_CIDRS` (default `192.168.4.0/24,100.64.0.0/10,127.0.0.1/32`), or `CF-Connecting-IP` within `ALLOWED_PUBLIC_IPS` (default `180.150.112.113`). Everything else returns 403. Values come from `.env`.
- Mutating endpoints additionally require `Authorization: Bearer $API_WRITE_TOKEN`. The frontend gets the token through a one-time entry stored in `localStorage`.
- No Cloudflare Access.

## 10. Deployment

**One-time setup:**
- `.50`: run `deploy/bootstrap-vps.sh`, which installs `uv`, `uv python install 3.12`, creates `/opt/seek-hunter/{app,data,book-cv}`, `/opt/seek-hunter/.env` (`ANTHROPIC_API_KEY`, `API_WRITE_TOKEN`, `ALLOWED_*`, `TELEGRAM_TARGET=1635495359`), installs and enables the systemd units. The web service binds `0.0.0.0:8090`. System Python and OpenClaw are untouched.
- `.106`: register the self-hosted runner `vm100-seek-hunter` (labels `self-hosted, linux, x64, seek-hunter`) for `bookmountain/seek-hunter`. Add the deploy key from `book@.106` to `root@.50:~/.ssh/authorized_keys`; password auth/sshd config unchanged.
- `.106` cloudflared: add `seekhunter.bookmountain.work → http://192.168.4.50:8090` above the 404 catch-all, run `cloudflared tunnel route dns 07c09f06-eb9e-4ff1-af6f-e67de11a37f9 seekhunter.bookmountain.work`, validate, restart.

**CI/CD (`.github/workflows/ci-deploy.yml`, branch `main`):**
- `verify` (ubuntu-latest): `uv sync`, `ruff check`, `pytest`; `npm ci`, `npm test`, `npm run build`.
- `deploy` (needs verify, push to main, `runs-on: [self-hosted, seek-hunter]`):
  1. `npm ci && npm run build` in `frontend/`.
  2. rsync `backend/` and `frontend/dist/` to `root@192.168.4.50:/opt/seek-hunter/app/` (excluding `.env`, `data/`).
  3. rsync `/work/book-cv/latex/sections/` from vm100 to `/opt/seek-hunter/book-cv/sections/`.
  4. Over SSH: `uv sync --frozen`, `systemctl restart seekhunter-web`, `systemctl daemon-reload` if units changed.
  5. Health check: `curl -fsS http://192.168.4.50:8090/api/health`.

## 11. Testing

- **Sources:** parse saved fixtures (SEEK search JSON, GraphQL jobDetails, Jora search + detail HTML). No network in CI.
- **Filters:** table-driven cases: NV1 → excluded; "Westpac via recruiter" → bank; "no security clearance required" → not excluded; employer allowlist overrides blocklist.
- **Scoring:** deterministic outputs for fixed profile and job; alias matching; work-type weights.
- **LLM chain:** mocked providers covering Anthropic credit-exhausted (400/402/429) → OpenClaw → none → rule-only.
- **Notifier:** message formatting snapshot; outbox retry on non-zero exit from `openclaw`.
- **API:** IP allowlist (LAN allowed, unknown CF IP blocked, allowlisted CF IP allowed), write-token enforcement.
- **Manual:** `seekhunter run --dry-run` on `.50` for a live smoke test (never in CI).

## 12. Error handling summary

| Failure | Behavior |
|---|---|
| Source 403/429 | Backoff, then `degraded` for the run; others continue; noted in digest |
| All sources fail 3 runs in a row | ⚠️ health alert, at most once per 24 h |
| LLM provider unavailable or out of credit | Next provider; finally rule-only |
| `openclaw message send` fails | Queued in `outbox`, retried next run |
| Resume sections missing | Run aborts with a clear error in `runs.error` and an alert |

## 13. TODO (future sub-projects)

- **B, tailoring:** per-job tailored resume (select and reword bullets from `book-cv` LaTeX, build PDF) and cover letter, via the Anthropic API (Sonnet) with the OpenClaw/Codex fallback. Note the VPS disk constraint for LaTeX (consider building on vm100 or using `tectonic`).
- **C, insights:** dashboard comparing Adelaide / Melbourne / Sydney / Perth: volume, work-type mix, and skill demand (e.g. Java vs C#, what AI-engineer roles require), with gap analysis against Book's profile.

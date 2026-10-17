# SeekHunter — Market Insights (Sub-project C) Design

**Date:** 2026-10-17 · **Status:** Approved (autonomous build requested)

## Goal
Tell Book where demand is and what to learn: compare Adelaide / Melbourne / Sydney / Perth on volume, flexible-work share, pay, and skill demand (e.g. Java vs C#, what AI-engineer roles require), with a ranked gap list against his resume and trends over time.

## Data collection (separate from notifications)
- New table `market_jobs`: id, source ("seek"), external_id (unique with source), city ("adelaide|melbourne|sydney|perth"), keyword (search term that found it), title, company, work_type, salary_label, salary_min_hourly/salary_max_hourly (normalised AUD/hour; annual ÷ 1976, daily ÷ 7.6), listed_at, role_family (frontend|backend|fullstack|ai_ml|data|devops_cloud|mobile|qa|it_support|other, rule-based from title), skills (JSON list via `skills.extract_skills` on title + teaser/bullets, and on full description when details fetched), details_fetched (bool), first_seen_at, last_seen_at.
- New table `market_snapshots`: date, city, total, by_work_type JSON, by_role_family JSON, skill_counts JSON (over jobs with details), salary percentiles JSON — one row per city per day (computed after each market crawl), enabling trends.
- Market crawl `seekhunter market [--cities ...] [--dry-run]`: for each city ("All Adelaide SA", "All Melbourne VIC", "All Sydney NSW", "All Perth WA") × market keywords (default: "software engineer", "developer", "full stack", "frontend", "backend", "AI engineer", "data engineer", "devops", "IT support") × up to 2 SEEK search pages (daterange 14), upsert market_jobs; then fetch SEEK details for up to 40 not-yet-detailed jobs per city (newest first) to extract skills from the description; then write today's snapshot per city. Uses the polite client; never touches `jobs`/notifications. Runs under its own lock name ("market.lock"). Settings: `market_cities`, `market_keywords`, `market_details_per_city` (40), `market_enabled` (true).
- systemd: `seekhunter-market.timer` daily 02:30 Australia/Adelaide (RandomizedDelaySec 20min); deploy enables it.
- Adelaide data also benefits from the main crawl: include main `jobs` (Adelaide) skills when computing Adelaide skill counts? No — keep market data self-contained for comparability across cities.

## Analysis API (read-only, IP-gated)
- `GET /api/insights/overview?days=14` → per city: total, flexible share (part-time+contract+casual), work-type mix, role-family mix, hourly pay p25/p50/p75 (from salary-labelled jobs, with sample size), detailed sample size.
- `GET /api/insights/skills?city=adelaide&days=14&role_family=` → `[{skill, count, share, you_have}]` sorted desc (share = count / detailed jobs in scope), top 40.
- `GET /api/insights/compare?skills=Java,C%23&days=14` → per city share for each skill (head-to-head).
- `GET /api/insights/gaps?city=adelaide&days=14` → skills not in Book's profile ranked by share, each with example job titles (≤3) and which role families ask for it.
- `GET /api/insights/trends?city=adelaide&skills=Java,C%23,Python&weeks=8` → per snapshot date shares.
- `GET /api/insights/roles?city=adelaide&days=14` → per role family: count, flexible share, top 8 skills.
- Profile skills come from `profile.load_profile(env.resume_dir).skills`.

## Weekly brief
- `seekhunter insights-brief [--dry-run]` + `seekhunter-insights-brief.timer` Mondays 08:30 Adelaide: plain-text Telegram message (no emoji, short): per city totals and flexible share; top 5 skills in Adelaide with "you have" markers; biggest 3 gaps with share; one head-to-head line (Java vs C#, TypeScript vs JavaScript) for Adelaide vs the best city; "Best city for flexible roles: X (n%)". Link to /insights.
- OpenClaw skill: "what skills should I learn?" / "Java or C#?" / "is Melbourne better?" → read the insights endpoints and answer briefly.

## Website (Swiss mono; load the dataviz skill before building charts)
- New nav item "Insights" → `/insights`: city tabs (Adelaide default) + "Compare cities" view.
  - Overview strip: per-city cards (total, flexible %, median $/h, sample sizes) as a compact mono table.
  - Skill demand: horizontal bar chart top 20 for the selected city (bars ink, your skills in blue, others grey; share % labels; sample size note).
  - Head-to-head: a small multiples row for preset pairs (Java vs C#, TypeScript vs JavaScript, React vs Angular vs Vue, AWS vs Azure vs GCP, Python vs Node.js) across the 4 cities.
  - Gaps: ranked list of top 10 missing skills with share and example titles.
  - Roles: role family table (count, flexible %, top skills chips).
  - Trends: sparkline/line chart for selected skills once ≥2 snapshots exist; otherwise a note "Trends appear after a few daily snapshots".
- Hand-rolled SVG (no chart library) to keep the bundle small and style exact; accessible (labels, titles), AA contrast.

## Testing
Role family + salary normalisation unit tests; market crawl with fake source (upsert, details cap, snapshot rows, never touches jobs); analysis endpoints with seeded market_jobs; brief formatting; frontend tests for charts rendering data and empty states.

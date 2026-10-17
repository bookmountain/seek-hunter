---
name: seekhunter
description: "Book's job-hunt tracker (SeekHunter). Use when Book mentions jobs, a job #id from a SeekHunter digest, saving/hiding/applying, why a job fits, tailoring his resume or a cover letter for a job, job searches/filters, or asks what's new on SEEK/Jora."
metadata:
  {
    "openclaw":
      {
        "requires": { "bins": ["seekhunter-api"] },
      },
  }
---

# SeekHunter

SeekHunter crawls SEEK and Jora every 2 hours (07:00–21:00 Adelaide). It drops jobs needing security clearance, citizenship/PR, defence, or banks, scores the rest against Book's resume (part-time/contract/casual first because of his student visa), and posts digests to this Telegram chat. Each digest line looks like `#7 · 88 · Title` (job id · score · title), e.g. `#142 · 82 · Full Stack (Java) Developer`.

All access goes through the `seekhunter-api METHOD PATH [JSON]` command (localhost API; auth is handled). Never invent job data; read it from the API. Keep replies short.

## Read
- What's new: `seekhunter-api GET "/api/summary?hours=24"` (plain text, one job per line)
- One job in detail (fit, matched/missing skills, AI note, recruiter contact, competition, description): `seekhunter-api GET /api/jobs/142/brief`. The brief includes a `Recruiter: Name · phone · email` line when known and a `LinkedIn: <url>` line — a real profile URL when one was found, otherwise a LinkedIn search URL for that name/company. For SEEK ads with published applicant stats, it also includes a `Competition: N applicants (volume label) · resume % · cover letter % · checked <time>` line — SEEK's own "how many people applied" numbers. Jora ads and SEEK ads that haven't published stats yet have no `Competition:` line.
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

## Tailor resume + cover letter
SeekHunter can rewrite Book's resume for one job (reorders/trims skills, picks projects, rewords bullets, never invents facts) and write a cover letter, then send both PDFs to this chat.
- "tailor #7" / "resume for #7" / "cover letter for #7": `seekhunter-api POST "/api/jobs/7/tailor?send=1"` → `{"tailoring_id": N, "status": "queued", "reused": false}`. Reply that the tailored resume and cover letter PDFs will arrive here in about 1–2 minutes, plus the side-by-side view at https://seekhunter.bookmountain.work/jobs/7/tailor. Don't send the files yourself; SeekHunter does. `reused: true` means one was already running — it will still be delivered.
- "show changes for #7" / "what did you change for #7?": `seekhunter-api GET /api/jobs/7/tailorings` (newest first), take the first `id`, then `seekhunter-api GET /api/tailorings/{id}`. If `status` is `queued`/`running`, say it's still working (`progress`). If `failed`, say so with the first line of `error` and offer to retry. If `done`, summarise in a few lines from `changes`: the summary rewrite, reworded bullets (`status: "reworded"`), removed bullets, skill-order changes, projects included/excluded; then `keywords_matched`, `gaps`, and any `warnings` (validator notes — mention them, don't hide them).
- "send it again" / "resend #7": find the latest done tailoring as above, then `seekhunter-api POST /api/tailorings/{id}/send`.
- "show the cover letter for #7": read `cover_letter.text` from the tailoring detail and paste it.

## How to answer
- "why #142?" / "am I a fit?": read the brief, then explain the overlap and the gaps in 3–5 lines. Mention visa fit (hours flag) when relevant.
- "how many applied to #142?" / "how much competition on #142?": read the brief's `Competition:` line and report the applicant count, volume label, and resume/cover-letter percentages. If there's no `Competition:` line, say SEEK hasn't published applicant numbers for that ad (or it's a Jora ad, which never has them) — don't guess a number.
- "who's the recruiter for #142?" / "can I call them?": read the brief and answer with the recruiter's name (if known), their phone number (call it out as tap-to-call), and their LinkedIn — a profile link if one was found, otherwise the LinkedIn search link. Don't invent a name, phone, or profile that isn't in the brief; if nothing is known, say so and offer the LinkedIn search link only.
- Before destructive changes (deleting searches, editing blocklists), restate the change in one line and do it. If ambiguous, ask.
- When Book states a lasting preference ("no recruiter X", "only contract"), apply it via settings/searches and remember it.
- Don't touch other cron jobs or channels.

## Market insights ("what skills should I learn?", "Java or C#?", "is Melbourne better?")
SeekHunter also runs a separate daily crawl of SEEK across Adelaide, Melbourne, Sydney, and Perth purely for
market stats (volume, flexible-work share, pay, skill demand) — this data never touches jobs or digests.
- City snapshot (totals, flexible %, pay percentiles, work-type/role mix): `seekhunter-api GET "/api/insights/overview?days=14"` → one row per city.
- What skills are in demand: `seekhunter-api GET "/api/insights/skills?city=adelaide&days=14"` → `[{skill, count, share, you_have}]`, sorted most in-demand first. Add `&role_family=ai_ml|data|devops_cloud|mobile|qa|it_support|frontend|backend|fullstack` to narrow it.
- Head-to-head (e.g. "Java or C#?"): `seekhunter-api GET "/api/insights/compare?skills=Java,C%23&days=14"` → the share of ads asking for each skill, per city.
- Gaps against Book's resume ("what should I learn?"): `seekhunter-api GET "/api/insights/gaps?city=adelaide&days=14"` → skills not in his resume, ranked by demand, each with up to 3 example titles and which role families ask for it.
- Trends over time: `seekhunter-api GET "/api/insights/trends?city=adelaide&skills=Java,C%23&weeks=8"` (needs a few days of daily snapshots to show more than one point).
- Role families ("is there more frontend or backend work?"): `seekhunter-api GET "/api/insights/roles?city=adelaide&days=14"` → count, flexible %, and top skills per role family.
- Answer in 3–6 plain-text lines, no emoji: cite the actual numbers (don't round away the sample size), and point to https://seekhunter.bookmountain.work/insights for the charts. If a city/role has too few jobs to be meaningful, say so rather than overstating a tiny sample.

## Research a job ("research #142", "tell me about the company for #142")
1. Read the job: `seekhunter-api GET /api/jobs/142/brief`.
2. Web-search the employer. If it is a recruitment agency, research the agency and name the end client only if the ad reveals it. Find what the company does, rough size, notable news from the last 6 months, and tech stack signals (their engineering blog, GitHub, other job ads).
3. Reply in plain text, no emoji, at most 8 lines: What they do / Recent / Stack / Recruiter (name · phone from the brief, or LinkedIn search link) / Competition (applicants from the brief) / Apply angle (one line). Never invent facts; write "not found" when unsure.
4. Offer: `Reply "tailor 142" for a tailored resume and cover letter.`

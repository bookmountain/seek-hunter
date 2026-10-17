---
name: seekhunter
description: "Book's job-hunt tracker (SeekHunter). Use when Book mentions jobs, a job #id from a SeekHunter digest, saving/hiding/applying, why a job fits, job searches/filters, or asks what's new on SEEK/Jora."
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

## How to answer
- "why #142?" / "am I a fit?": read the brief, then explain the overlap and the gaps in 3–5 lines. Mention visa fit (hours flag) when relevant.
- "how many applied to #142?" / "how much competition on #142?": read the brief's `Competition:` line and report the applicant count, volume label, and resume/cover-letter percentages. If there's no `Competition:` line, say SEEK hasn't published applicant numbers for that ad (or it's a Jora ad, which never has them) — don't guess a number.
- "who's the recruiter for #142?" / "can I call them?": read the brief and answer with the recruiter's name (if known), their phone number (call it out as tap-to-call), and their LinkedIn — a profile link if one was found, otherwise the LinkedIn search link. Don't invent a name, phone, or profile that isn't in the brief; if nothing is known, say so and offer the LinkedIn search link only.
- Before destructive changes (deleting searches, editing blocklists), restate the change in one line and do it. If ambiguous, ask.
- When Book states a lasting preference ("no recruiter X", "only contract"), apply it via settings/searches and remember it.
- Don't touch other cron jobs or channels.

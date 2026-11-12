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

SeekHunter crawls SEEK, Jora, LinkedIn and Indeed every 2 hours (07:00–21:00 Adelaide). It drops jobs needing security clearance, citizenship/PR, defence, or banks, scores the rest against Book's resume (part-time/contract/casual first because of his student visa), and posts digests to this Telegram chat. Each digest line looks like `#7 · 88 · Title` (job id · score · title), e.g. `#142 · 82 · Full Stack (Java) Developer`.

All access goes through the `seekhunter-api METHOD PATH [JSON]` command (localhost API; auth is handled). Never invent job data; read it from the API. Keep replies short.

## Read
- What's new: `seekhunter-api GET "/api/summary?hours=24"` (plain text, one job per line)
- One job in detail (fit, matched/missing skills, AI note, recruiter contact, competition, description): `seekhunter-api GET /api/jobs/142/brief`. The brief includes a `Recruiter: Name · phone · email` line when known and a `LinkedIn: <url>` line — a real profile URL when one was found, otherwise a LinkedIn search URL for that name/company. For SEEK ads with published applicant stats, it also includes a `Competition: N applicants (volume label) · resume % · cover letter % · checked <time>` line — SEEK's own "how many people applied" numbers. Jora ads and SEEK ads that haven't published stats yet have no `Competition:` line.
- List as JSON: `seekhunter-api GET "/api/jobs?view=active&status=saved"` (`view=excluded` for excluded; filters: `work_type=part_time|contract|casual|full_time`, `source=seek|jora|linkedin|indeed|radar`, `q=text`, `city=adelaide|melbourne|sydney|perth|other`, e.g. `seekhunter-api GET "/api/jobs?city=melbourne"`). Counts per city for the same view: `seekhunter-api GET "/api/jobs/cities?view=active"` → `[{"city":"adelaide","count":12}, ...]`.
- Searches: `seekhunter-api GET /api/search-profiles`
- Settings: `seekhunter-api GET /api/settings`
- Recent runs/health: `seekhunter-api GET /api/runs`

## Act
- Status: `seekhunter-api PATCH /api/jobs/142 '{"status":"saved"}'` (`saved|applied|hidden|new`); notes: `'{"notes":"..."}'`
- Wrongly excluded job: `seekhunter-api POST /api/jobs/142/unexclude '{"allowlist_employer":false}'`
- Add a search: `seekhunter-api POST /api/search-profiles '{"name":"Melbourne · react","keywords":"react","location":"All Melbourne VIC","work_types":[],"sources":["seek","jora"],"enabled":true}'` (locations: "All Adelaide SA", "All Melbourne VIC", "All Sydney NSW", "All Perth WA"; work_types empty = all)
- Change a search: GET it from the list, then `PUT /api/search-profiles/{id}` with the full object
- Settings (blocklists, weights, toggles): GET `/api/settings`, modify the field, then `PUT /api/settings` with the **full** JSON (never send a partial object)
- "enable Melbourne notifications" / "send me Sydney jobs too": SeekHunter already crawls, scores, and evaluates Melbourne/Sydney/Perth jobs (search profiles exist for all four cities) — only Telegram delivery is gated by `notify_cities` (default `["adelaide"]`). `seekhunter-api GET /api/settings`, add the city (lowercase, e.g. `"melbourne"`) to `notify_cities`, then `PUT /api/settings` with the full JSON. Only jobs first seen in the last 48h get notified once a city is enabled — it never floods the chat with a backlog. "stop Melbourne notifications" is the same flow, removing the city instead.
- Run a crawl now: `seekhunter-api POST /api/runs`

## Company Radar ("radar companies", "add <company> to radar")
Besides SEEK, Jora, LinkedIn and Indeed, SeekHunter polls employers' own job feeds (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Workday) every 30 minutes, 07:00–22:00 Adelaide, so their ads are often seen before the boards. Strong new jobs (score 70+, 20 or fewer applicants, posted in the last 24 h, Adelaide) arrive as single "Just posted · #id · score · title — company · type · source" messages; jobs with source `radar` came from the employer's own careers feed.
- "radar companies" / "what's on the radar?": `seekhunter-api GET /api/radar/companies` → `[{id, name, ats, ats_token, careers_url, enabled, last_checked_at, last_error, last_job_count}]`. Summarise: how many enabled, by ATS, and any with `last_error`.
- "add <Company> to radar": `seekhunter-api POST /api/radar/companies '{"name":"<Company>","careers_url":"<careers page URL if Book gave one>"}'`. SeekHunter detects the ATS itself. Report the result's `ats` and `ats_token`; `ats` "other" or "pageup" means there is no feed to poll, so it is watched through changedetection.io instead (Book runs the watch sync). If `last_error` says no ATS was found and there's no careers URL, ask Book for the careers page link.
- "remove <Company> from radar" / "pause <Company>": find its id in the list, then `seekhunter-api DELETE /api/radar/companies/{id}` or `seekhunter-api PATCH /api/radar/companies/{id} '{"enabled":false}'`.
- "check <Company> now": `seekhunter-api POST /api/radar/companies/{id}/check` (runs in the background; any new matches arrive as normal alerts).
- "fill the radar" / "seed the radar": `seekhunter-api POST /api/radar/seed` — probes direct employers (recruitment agencies are skipped) from the last 60 days of jobs; takes a few minutes.

## Application history (applications, contacts, companies)
SeekHunter tracks what Book has applied to, the recruiter/HR contacts he's dealt with, and which companies already have his resume — so he never double-applies through the same agency and can follow up on time.
- "applied #7" / "mark #7 applied": `seekhunter-api PATCH /api/jobs/7 '{"status":"applied"}'`. This auto-creates the application (idempotent — safe to send twice), attaches the latest tailored resume for that job if one was done, and upserts the job's recruiter (if a name is known) as a contact linked to the job.
- "applied to <Company> for <Title>" (a job outside SeekHunter, e.g. one he found elsewhere): `seekhunter-api POST /api/applications '{"company":"<Company>","title":"<Title>","url":"<url if known>","notes":"<optional>"}'`. If he names who he dealt with, add `"contact":{"name":"<Name>","role":"Recruiter","phone":"<optional>","email":"<optional>"}`.
- "move #7 to interview" / "<Company> application is now rejected": find the application id — it's on the job as `application.id` (`GET /api/jobs/7`), or search `seekhunter-api GET "/api/applications?q=<company or title>"` — then `seekhunter-api PATCH /api/applications/{id} '{"stage":"interview"}'` (stages: `applied`, `screening`, `interview`, `offer`, `rejected`, `withdrawn`, `no_response`).
- "called Brayden" / "emailed Jerry" / "sent LinkedIn invite to Sam": find the contact first — `seekhunter-api GET "/api/contacts?q=Brayden"`. If exactly one match, log it: `seekhunter-api POST /api/interactions '{"contact_id":<id>,"kind":"call","note":"<optional>"}'` (kinds: `call`, `voicemail`, `email`, `linkedin_invite`, `linkedin_accepted`, `linkedin_message`, `linkedin_reply`, `meeting`, `note`). If the search returns zero or more than one match, ask Book which contact/company he means before logging anything — never guess which contact or invent one.
- "log a call with #7's recruiter" (still just a contact on the job ad, not yet saved separately): `seekhunter-api POST /api/jobs/7/contact-log '{"kind":"call","note":"<optional>"}'` — upserts the job's recruiter as a contact and logs the interaction in one call.
- "what's my pipeline?" / "anything going stale?": `seekhunter-api GET "/api/history/summary?days=14"` (plain text: counts by stage, recent applications, recent interactions, and a short list of follow-ups due).
- "who should I follow up?" / "follow-ups" / "what's due?": `seekhunter-api GET /api/follow-ups/summary` (plain text: every follow-up due, each with its `key`, contact, channel and a ready-to-send message). Kinds: Nudge (application still `applied` with no activity for 5+ days), Invite pending (LinkedIn invite not accepted after 5+ days), Say thanks (invite accepted, no message yet), No reply (LinkedIn message unanswered for 5+ days). List them briefly (company · role · contact · days) and paste the message for the one he picks, exactly as given; don't add claims to it. If nothing is due, say so.
- "sent it" / "done with the <Company> follow-up": `seekhunter-api POST /api/follow-ups/{key}/done '{"note":"<optional>"}'` (logs the email/LinkedIn message/call and starts the next cycle). "snooze <Company> for a week": `seekhunter-api POST /api/follow-ups/{key}/snooze '{"days":7}'` (default 3). "skip it" / "not worth it": `seekhunter-api POST /api/follow-ups/{key}/dismiss`. Take the key from the summary; if more than one item could match, ask which.
- LinkedIn progress is tracked per contact (sent → accepted → messaged → replied, shown as `linkedin_status` on `GET /api/contacts`): log "Sam accepted" as `linkedin_accepted`, "messaged Sam" as `linkedin_message`, "Sam replied on LinkedIn" as `linkedin_reply`. "left Brayden a voicemail" is kind `voicemail` (a call that didn't connect).
- "how's my response rate?" / "is calling the recruiter worth it?" / "agency or direct?": `seekhunter-api GET /api/funnel` (optionally `?days=90`) → `total` and `by_source`, `by_employer` (agency/direct), `by_work_type`, `by_call` (called / voicemail / not called before or at applying); each row has `applied`, `responded`, `interview`, `offer` and the two rates. Always quote the counts with the rates (e.g. "2 of 3 (67%)") and say plainly when a group has fewer than 5 applications that it's too few to read anything into. Page: https://seekhunter.bookmountain.work/history?tab=funnel.
- "who have I applied to at <Company>?" / "does <Company> already have my resume?": `seekhunter-api GET "/api/companies?q=<Company>"` → each row has `applications` (title/stage/applied_at) and `contacts` for that company.
- Full lists when needed: `GET /api/applications`, `GET /api/contacts`, `GET /api/history?limit=100` (unified timeline, newest first).

## Recruiter call script ("call script for #12", "what do I say to the recruiter for #12?")
Calling the recruiter before or right after applying raises Book's odds, so each job has a call script: 3 questions to ask about this specific job and a ~20-second pitch built only from his resume, ending with a fixed, honest line about his student visa (up to 48 hours a fortnight during semester, full-time in uni holidays).
- `seekhunter-api POST /api/jobs/12/call-script` → `{questions: [3], pitch, source, warnings, agency}`. It generates with the AI once and caches it (later calls return the cached one quickly; add `?refresh=1` only if he asks for a new one). `source: "template"` means the AI was unavailable and a deterministic script was used; it's still accurate.
- Reply in plain text: the recruiter's name and tap-to-call phone (from the brief, `GET /api/jobs/12/brief`) if known, then "Pitch:" with the pitch verbatim, then the 3 questions numbered. Never add skills, employers, years or visa claims beyond what the script says; mention any `warnings` in one line.
- After the call: "called #12's recruiter" → `seekhunter-api POST /api/jobs/12/contact-log '{"kind":"call","note":"<what they said, optional>"}'`; "left a voicemail for #12" → same with `"kind":"voicemail"`. The job needs a named recruiter for this; if it has none, say so.

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

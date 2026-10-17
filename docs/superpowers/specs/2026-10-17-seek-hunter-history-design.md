# SeekHunter — Application History (Sub-project E) Design

**Date:** 2026-10-17 · **Status:** Approved (user request; autonomous build)

## Goal
Track what Book has applied to, which HR/recruiters he has contacted, and which companies already have his resume — so he never double-applies through the same agency and can follow up.

## Data model (new tables; created by create_all)
- `applications`: id, job_id (nullable, FK jobs.id), company, company_key (normalised: lowercase, strip pty/ltd/limited/group/australia/au/state suffixes and punctuation — reuse `domain.dedupe_key` company logic), title, url, location, applied_at (NaiveDatetime), tailoring_id (nullable, FK tailorings.id), stage (`applied|screening|interview|offer|rejected|withdrawn|no_response`), source (`seekhunter|manual`), notes, created_at, updated_at. Unique: (job_id) when job_id not null.
- `contacts`: id, name, company, company_key, role (e.g. "Recruiter"), phone, email, linkedin, notes, created_at, updated_at. Unique-ish on (lower(name), company_key); upsert merges missing fields.
- `contact_jobs`: contact_id, job_id (link table; contact appears on these ads).
- `interactions`: id, contact_id (nullable), application_id (nullable), kind (`call|email|linkedin_invite|linkedin_accepted|linkedin_message|meeting|note`), at (NaiveDatetime, default now), note, created_at.
- `application_events`: id, application_id, kind (`created|stage_changed|note`), from_stage, to_stage, at, note — powers the timeline.

## Behaviour
- Setting a job's status to `applied` (PATCH /api/jobs/{id}) auto-creates the application (if none) with applied_at=now, company/title/url/location from the job, tailoring_id = latest done tailoring for that job (if any), and upserts the job's recruiter (contact_name/phone/email/linkedin) as a contact linked to the job. Moving status away from applied does NOT delete the application.
- Recruiter contacts found on any job are upserted into `contacts` during the crawl/backfill only when a name exists (phone-only contacts stay on the job), with `contact_jobs` links.
- "Company already has your resume": any application whose company_key equals the job's company_key (excluding the job's own application). Exposed on JobOut as `prior_applications: [{application_id, title, applied_at, stage}]` (most recent first, max 5).

## API (write = token)
- `GET /api/applications?stage=&q=` · `POST /api/applications` (manual: company, title, url?, location?, applied_at?, notes?, contact?) · `PATCH /api/applications/{id}` (stage, notes, applied_at, tailoring_id) · `DELETE /api/applications/{id}`.
- `GET /api/contacts?q=` (each with last_interaction, interaction_count, job_count, application_count) · `POST /api/contacts` · `PATCH /api/contacts/{id}` · `GET /api/contacts/{id}` (with interactions + linked jobs/applications).
- `POST /api/interactions` (contact_id and/or application_id, kind, at?, note?) · `DELETE /api/interactions/{id}`. Convenience: `POST /api/jobs/{id}/contact-log` (kind, note) upserts the job's recruiter as a contact then logs the interaction.
- `GET /api/companies?q=` → `[{company, company_key, application_count, last_applied_at, applications:[{id,title,applied_at,stage,tailoring_id}], contacts:[{id,name}]}]` sorted by last_applied_at desc.
- `GET /api/history?limit=100` → unified timeline of application_events + interactions, newest first: `{at, type, kind, company, title, contact_name, application_id, contact_id, note, from_stage, to_stage}`.
- JobOut gains `prior_applications` and `application` (this job's application summary or null).
- Plain-text for agents: `GET /api/history/summary?days=14` (applications by stage, recent interactions, follow-ups due: applications in `applied` with no event for ≥7 days).

## Notifications
- Digest: when a job's company already has Book's resume, add a line `Already applied: <title> (<n>d ago)` under the company line.
- Recap/weekly brief: optional "Follow up" line listing up to 3 applications in `applied` stage older than 7 days with no interaction.

## OpenClaw skill
- "applied #7" → PATCH status applied. "applied to <company> for <title>" (outside SeekHunter) → POST /api/applications. "called Brayden" / "emailed Jerry" / "sent LinkedIn invite to Sam" → find contact via GET /api/contacts?q= then POST /api/interactions (ask if ambiguous). "move #7 to interview" → PATCH application stage. "what's my pipeline?" / "who should I follow up?" → GET /api/history/summary.

## Website (Swiss mono; same components/style)
- Nav "HISTORY" → `/history` with tabs: Applications | Contacts | Companies | Timeline.
  - Applications: table (applied date, company, role, stage select inline, resume link → tailoring page, contact, last activity); filter by stage; "Add application" form (manual).
  - Contacts: table (name, company, phone tel:, email, LinkedIn, last interaction, counts); row expands to interaction log + quick log buttons (Called, Emailed, LinkedIn invite, Invite accepted, Note) and linked jobs/applications; "Add contact".
  - Companies: list (company, applications count, last applied, roles + stages, contacts).
  - Timeline: chronological feed grouped by day.
- Job list row: a small mono "APPLIED" tag if this job has an application, or "HAS RESUME" (grey) if the company does.
- Job detail: warning box when prior_applications exist ("Robert Walters already has your resume: Full Stack (Java) Developer · 3d ago · interview"); Recruiter block gets quick log buttons (Called, Emailed, LinkedIn invite) that call contact-log; when the job is applied, show the application stage control.

## Testing
Model/upsert/company_key; auto-create on applied with tailoring + contact; prior_applications; endpoints; timeline ordering; digest line; skill doc. Frontend: tabs render, stage change PATCH, quick log POST, warning box.

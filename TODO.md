# TODO

- [x] **A — Core**: SEEK + Jora crawler, filters, scoring, Telegram via OpenClaw, web UI, deploy (spec: `docs/superpowers/specs/2026-10-17-seek-hunter-core-design.md`)
- [ ] **B — Tailoring**: per-job tailored resume (from `book-cv` LaTeX) + cover letter via Anthropic API, OpenClaw/Codex fallback; "tailor #id" in Telegram via the OpenClaw skill, PDFs sent with `openclaw message send --media`
- [ ] **C — Insights**: Adelaide / Melbourne / Sydney / Perth comparison, skill-demand trends (e.g. Java vs C#, AI engineer requirements), gap analysis vs profile
- [ ] **D — OpenClaw research**: "research #id" company briefs via OpenClaw web search (news, tech stack, size); repoint or retire the noon OpenClaw SEEK job to read from SeekHunter
- [ ] **F — Multi-city jobs feed**: Melbourne/Sydney/Perth search profiles in the main crawl (scored, filtered), `jobs.city`, Jobs page location filter with counts, `notify_cities` setting (default Adelaide) so Telegram stays Adelaide-only unless enabled; in-app navbar notification bell (new jobs since last read across all cities with per-city counts, tailoring done, follow-ups due; server-side last-read marker; mark all read)

import type { RadarAts, RadarCompany } from "./types";

export const ATS_LABEL: Record<RadarAts, string> = {
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  workable: "Workable",
  smartrecruiters: "SmartRecruiters",
  workday: "Workday",
  pageup: "PageUp",
  other: "Other page",
};

/** ATS kinds the radar polls itself; the rest are watched by changedetection.io. */
export const POLLED: ReadonlySet<RadarAts> = new Set(["greenhouse", "lever", "ashby", "workable", "smartrecruiters", "workday"]);

export function radarStats(rows: RadarCompany[]) {
  const on = rows.filter((c) => c.enabled);
  return {
    total: rows.length,
    polled: on.filter((c) => POLLED.has(c.ats)).length,
    watched: on.filter((c) => !POLLED.has(c.ats)).length,
    paused: rows.length - on.length,
    errors: rows.filter((c) => c.last_error).length,
    jobs: on.reduce((n, c) => n + (c.last_job_count ?? 0), 0),
  };
}

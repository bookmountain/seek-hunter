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
  contact_name: string | null;
  /** Local AU format, e.g. "08 8216 3534". */
  contact_phone: string | null;
  contact_email: string | null;
  /** A likely linkedin.com/in/ profile URL, when one was found. */
  contact_linkedin: string | null;
  /** Always has a LinkedIn people-search URL; `google` only when a name exists. */
  contact_search: { linkedin: string; google?: string };
  /** SEEK's "how many people applied" stats; always null for Jora and for SEEK ads SEEK hasn't
   * published stats for. */
  applicant_count: number | null;
  /** SEEK's volume label, e.g. "Medium application volume". */
  applicant_volume: string | null;
  resume_pct: number | null;
  cover_letter_pct: number | null;
  insights_checked_at: string | null;
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
  max_insights_per_run: number;
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

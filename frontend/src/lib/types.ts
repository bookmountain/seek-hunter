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

// ---------------------------------------------------------------- tailoring

export type TailoringStatus = "queued" | "running" | "done" | "failed";

export interface TailoringSummary {
  id: number;
  job_id: number;
  status: TailoringStatus;
  /** "Reading resume" | "Rendering current resume" | "Tailoring with AI" | "Compiling PDFs" | "Sending to Telegram" | "Done" | "Failed" */
  progress: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  provider: string | null;
  error: string | null;
  send_requested: boolean;
  sent_at: string | null;
  resume_hash: string | null;
  /** Empty until done. */
  pages: { resume?: number; cover_letter?: number };
  warnings_count: number;
}

export interface TailorStart {
  tailoring_id: number;
  status: TailoringStatus;
  reused: boolean;
}

export interface ResumeCurrent {
  hash: string | null;
  ready: boolean;
  pages: number;
  pdf_url: string | null;
  page_urls: string[];
  error: string | null;
}

export interface CoverLetter {
  greeting: string;
  paragraphs: string[];
  sign_off: string;
  text: string;
  word_count: number;
}

export interface SummaryChange {
  type: "summary";
  before: string;
  after: string;
  changed: boolean;
}

export interface BulletChange {
  type: "bullet";
  experience: string;
  company: string;
  id: string;
  status: "kept" | "reworded" | "removed";
  before: string;
  after: string | null;
}

export interface SkillsChange {
  type: "skills";
  id: string;
  category: string;
  before: string[];
  after: string[];
  changed: boolean;
}

export interface ProjectsChange {
  type: "projects";
  included: string[];
  excluded: string[];
}

export type TailoringChange = SummaryChange | BulletChange | SkillsChange | ProjectsChange;

export interface TailoringDetail extends TailoringSummary {
  job: { id: number; title: string; company: string; location: string; work_type: WorkType; contact_name: string | null };
  warnings: string[];
  keywords_matched: string[];
  gaps: string[];
  /** null until done */
  cover_letter: CoverLetter | null;
  /** [] until done */
  changes: TailoringChange[];
  files: { resume_pdf: string; cover_letter_pdf: string; resume_pages: string[]; cover_letter_pages: string[] } | null;
  current: ResumeCurrent | null;
}

// ---------------------------------------------------------------- market insights

export type City = "adelaide" | "melbourne" | "sydney" | "perth";

export interface CityOverview {
  city: City;
  total: number;
  flexible: number;
  /** 0–1 */
  flexible_share: number;
  work_type_mix: Record<string, number>;
  role_family_mix: Record<string, number>;
  /** AUD per hour */
  salary_p25: number | null;
  salary_p50: number | null;
  salary_p75: number | null;
  salary_sample_size: number;
  detailed_sample_size: number;
}

export interface SkillShare {
  skill: string;
  count: number;
  /** 0–1 */
  share: number;
  you_have: boolean;
}

export interface CompareResult {
  skills: string[];
  cities: { city: City; shares: Record<string, number>; detailed_sample_size: number }[];
}

export interface SkillGap {
  skill: string;
  count: number;
  share: number;
  example_titles: string[];
  role_families: string[];
}

export interface TrendsResult {
  city: City;
  skills: string[];
  points: { date: string; shares: Record<string, number> }[];
}

export interface RoleFamilyRow {
  role_family: string;
  count: number;
  flexible_share: number;
  top_skills: string[];
}

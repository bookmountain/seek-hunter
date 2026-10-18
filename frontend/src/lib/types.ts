export type WorkType = "full_time" | "part_time" | "contract" | "casual" | "unknown";
export type JobStatus = "new" | "saved" | "applied" | "hidden";
export type JobCity = "adelaide" | "melbourne" | "sydney" | "perth" | "brisbane" | "other";

export interface Job {
  id: number;
  source: "seek" | "jora" | "linkedin";
  title: string;
  company: string;
  location: string;
  /** Normalised city the job is in. */
  city: JobCity;
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
  /** This job's own application, when it has been applied to. */
  application: ApplicationSummary | null;
  /** Earlier applications to the same company (max 5). */
  prior_applications: PriorApplication[];
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
  sources: ("seek" | "jora" | "linkedin")[];
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
  /** Cities that trigger Telegram alerts (others still show on the site and in the bell). */
  notify_cities: string[];
  other_city_max_pages: number;
  /** Server-owned bell marker; preserved by the server on PUT. */
  notifications_read_at: string | null;
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
  unknown: "Not stated",
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

export interface DiffOp {
  op: "equal" | "delete" | "insert";
  text: string;
}

export interface SummaryChange {
  type: "summary";
  before: string;
  after: string;
  changed: boolean;
  /** Word-level diff (newer backends). */
  diff?: DiffOp[];
}

export interface HeadlineChange {
  type: "headline";
  after: string;
}

export interface BulletChange {
  type: "bullet";
  experience: string;
  company: string;
  id: string;
  status: "kept" | "reworded" | "removed" | "moved";
  before: string;
  after: string | null;
  diff?: DiffOp[];
  position_before?: number;
  position_after?: number;
}

export interface ChangeCounts {
  reworded: number;
  removed: number;
  moved: number;
  skills_reordered: number;
  projects_changed: number | boolean;
  summary_changed: boolean;
  headline_added?: boolean;
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

export type TailoringChange = HeadlineChange | SummaryChange | BulletChange | SkillsChange | ProjectsChange;

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
  change_counts?: ChangeCounts;
  /** Resume-Matcher's ATS formula on the current and tailored resume; nulls until done. */
  ats?: AtsPair;
  /** null when Resume-Matcher never ran for this tailoring (disabled, or older run). */
  resume_matcher?: ResumeMatcherResult | null;
}

export interface AtsBreakdown {
  keyword_match: number | null;
  skills_coverage: number | null;
  title_alignment: number | null;
  section_completeness: number | null;
  date_consistency: number | null;
}

export interface AtsScore {
  score: number;
  breakdown: AtsBreakdown;
  missing_keywords: string[];
  matched_keywords: string[];
}

export interface AtsPair {
  current: AtsScore | null;
  tailored: AtsScore | null;
  /** Whose keyword list was scored against: SeekHunter's own analysis, or Resume-Matcher's extraction. */
  keywords_source: "seekhunter" | "resume_matcher" | null;
}

export interface InterviewQuestion {
  question: string;
  focus_area?: string | null;
  suggested_answer_points: string[];
}

export interface InterviewPrep {
  role_fit_analysis?: string[];
  resume_questions?: InterviewQuestion[];
  project_follow_ups?: InterviewQuestion[];
  skill_gaps?: { skill: string; why_it_matters: string; preparation_suggestion: string }[];
  talking_points?: string[];
}

export type ResumeMatcherRunStatus = "queued" | "running" | "done" | "failed" | "unavailable";

export interface ResumeMatcherResult {
  status: ResumeMatcherRunStatus;
  error: string | null;
  warnings: string[];
  started_at: string | null;
  finished_at: string | null;
  ats_score: number | null;
  sub_scores: Record<string, number | null>;
  matched_keywords: string[];
  missing_keywords: string[];
  injectable_keywords: string[];
  recommendations: string[];
  interview_prep: InterviewPrep | null;
  outreach_message: string | null;
  rm_master_id: string | null;
  rm_job_id: string | null;
  rm_resume_id: string | null;
  /** Link to the tailored resume inside Resume-Matcher. */
  rm_url: string | null;
}

export interface ResumeMatcherHealth {
  enabled: boolean;
  reachable: boolean;
  ready: boolean;
  llm_configured: boolean;
  llm_healthy: boolean;
  status: string | null;
  base_url: string | null;
  settings_url: string | null;
  error: string | null;
}

export interface TailoringListItem extends TailoringSummary {
  job_title: string;
  company: string;
  city: JobCity | null;
  resume_pdf: string | null;
  cover_letter_pdf: string | null;
  /** Page-1 PNG URL, when done. */
  thumbnail: string | null;
  applied_application_id: number | null;
  /** ATS score (Resume-Matcher formula) of the current and the tailored resume, when done. */
  ats_current?: number | null;
  ats_tailored?: number | null;
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

// ---------------------------------------------------------------- application history

export const APPLICATION_STAGES = ["applied", "screening", "interview", "offer", "rejected", "withdrawn", "no_response"] as const;
export type ApplicationStage = (typeof APPLICATION_STAGES)[number];

export const INTERACTION_KINDS = ["call", "email", "linkedin_invite", "linkedin_accepted", "linkedin_message", "meeting", "note"] as const;
export type InteractionKind = (typeof INTERACTION_KINDS)[number];

export interface ApplicationSummary {
  id: number;
  stage: ApplicationStage;
  applied_at: string;
  tailoring_id: number | null;
  notes: string;
}

export interface PriorApplication {
  application_id: number;
  title: string;
  applied_at: string;
  stage: ApplicationStage;
}

export interface Application {
  id: number;
  job_id: number | null;
  company: string;
  company_key: string;
  title: string;
  url: string | null;
  location: string | null;
  applied_at: string;
  tailoring_id: number | null;
  stage: ApplicationStage;
  source: string;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface ContactIn {
  name: string;
  role?: string | null;
  phone?: string | null;
  email?: string | null;
  linkedin?: string | null;
}

export interface ApplicationCreate {
  company: string;
  title: string;
  url?: string | null;
  location?: string | null;
  applied_at?: string | null;
  notes?: string;
  contact?: ContactIn | null;
}

export interface Contact {
  id: number;
  name: string;
  company: string;
  company_key: string;
  role: string | null;
  phone: string | null;
  email: string | null;
  linkedin: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
  last_interaction: string | null;
  interaction_count: number;
  job_count: number;
  application_count: number;
}

export interface Interaction {
  id: number;
  contact_id: number | null;
  application_id: number | null;
  kind: InteractionKind;
  at: string;
  note: string;
  created_at: string;
}

export interface ContactDetail extends Contact {
  interactions: Interaction[];
  jobs: { id: number; title: string; company: string; url: string }[];
  applications: Application[];
}

export interface CompanyHistory {
  company: string;
  company_key: string;
  application_count: number;
  last_applied_at: string;
  applications: { id: number; title: string; applied_at: string; stage: ApplicationStage; tailoring_id: number | null }[];
  contacts: { id: number; name: string }[];
}

export interface HistoryEvent {
  at: string;
  type: "event" | "interaction";
  /** event: created | stage_changed | note; interaction: an InteractionKind */
  kind: string;
  company: string | null;
  title: string | null;
  contact_name: string | null;
  application_id: number | null;
  contact_id: number | null;
  note: string;
  from_stage: string | null;
  to_stage: string | null;
}

// ---------------------------------------------------------------- notifications

export interface CityCount {
  city: JobCity;
  count: number;
}

export interface NotificationItem {
  type: "job" | "tailoring" | "follow_up";
  at: string;
  title: string;
  subtitle: string;
  city?: JobCity | null;
  score?: number | null;
  job_id?: number | null;
  tailoring_id?: number | null;
  application_id?: number | null;
  unread: boolean;
}

export interface NotificationsResult {
  read_at: string;
  unread_count: number;
  by_city: CityCount[];
  items: NotificationItem[];
}

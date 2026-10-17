import { since } from "@/lib/format";
import type { Job } from "@/lib/types";

type Competition = Pick<
  Job,
  "source" | "applicant_count" | "applicant_volume" | "resume_pct" | "cover_letter_pct" | "insights_checked_at"
>;

function Bar({ label, pct }: { label: string; pct: number }) {
  return (
    <div className="flex items-center gap-3">
      <span className="kicker w-28 shrink-0 text-ink-muted">{label}</span>
      <span className="h-3 flex-1 border border-ink" aria-hidden>
        <span className="block h-full bg-ink" style={{ width: `${pct}%` }} />
      </span>
      <span className="num w-10 shrink-0 text-right text-[13px] text-ink">{pct}%</span>
    </div>
  );
}

/** SEEK's applicant-count/resume/cover-letter stats for this ad, when published. Jora never has
 * these; SEEK sometimes hasn't published them yet either. */
export function CompetitionBlock({ job }: { job: Competition }) {
  const count = job.applicant_count;
  const volume = job.applicant_volume;
  const resume = job.resume_pct;
  const coverLetter = job.cover_letter_pct;

  return (
    <section aria-labelledby="competition-label" className="mt-7 border-t-2 border-ink pt-4">
      <p id="competition-label" className="kicker text-ink-muted">
        Competition
      </p>

      {count === null ? (
        <p className="mt-2 text-[15px] text-ink-muted">
          {job.source === "jora"
            ? "SEEK only — not available for Jora ads"
            : "SEEK hasn't published applicant numbers for this ad"}
        </p>
      ) : (
        <>
          <div className="mt-2 flex items-baseline gap-3">
            <span className="num inline-block text-[40px] leading-none font-medium tracking-[-0.04em] text-ink">
              {count}
            </span>
            <div>
              <p className="text-[14px] font-medium text-ink">applicants</p>
              {volume && <p className="text-[12.5px] text-ink-muted">{volume}</p>}
            </div>
          </div>

          {(resume !== null || coverLetter !== null) && (
            <div className="mt-3 flex flex-col gap-2">
              {resume !== null && <Bar label="Resume" pct={resume} />}
              {coverLetter !== null && <Bar label="Cover letter" pct={coverLetter} />}
            </div>
          )}

          {coverLetter !== null && (
            <p className="mt-2 text-[12.5px] text-ink-muted">
              {100 - coverLetter}% of applicants skipped the cover letter
            </p>
          )}

          {job.insights_checked_at && (
            <p className="mt-2 text-[12px] text-ink-muted">checked {since(job.insights_checked_at)} ago</p>
          )}
        </>
      )}
    </section>
  );
}

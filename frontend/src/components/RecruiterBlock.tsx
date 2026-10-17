import type { Job } from "@/lib/types";
import { CopyButton } from "./CopyButton";
import { RecruiterQuickLog } from "./history/JobHistoryBits";

type Contact = Pick<
  Job,
  "company" | "contact_name" | "contact_phone" | "contact_email" | "contact_linkedin" | "contact_search"
>;

const telHref = (phone: string) => `tel:${phone.replace(/[^\d+]/g, "")}`;

function ExtLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex min-h-8 items-center text-[14px] font-medium text-blue underline-offset-4 hover:underline"
    >
      {children}&nbsp;<span aria-hidden>↗</span>
    </a>
  );
}

/** Recruiter contact pulled from the ad, plus LinkedIn/Google lookups. */
/** Pass `jobId` to enable quick logging (needs a QueryClient). */
export function RecruiterBlock({ job, jobId }: { job: Contact; jobId?: number }) {
  const { contact_name: name, contact_phone: phone, contact_email: email, contact_linkedin: profile } = job;
  const hasContact = !!(name || phone || email);
  const search = job.contact_search;

  return (
    <section aria-labelledby="recruiter-label" className="mt-7 border-t-2 border-ink pt-4">
      <p id="recruiter-label" className="kicker text-ink-muted">
        Recruiter
      </p>

      {hasContact ? (
        <div className="mt-2 flex items-start justify-between gap-4">
          <div className="min-w-0">
            {name ? (
              <p className="font-display text-[18px] leading-tight font-semibold tracking-[-0.01em]">{name}</p>
            ) : (
              <p className="text-[15px] text-ink-muted">Name not stated</p>
            )}
            <p className="mt-0.5 text-[13.5px] text-ink-muted">{job.company}</p>
          </div>
          {name && <CopyButton text={`${name}, ${job.company}`} label="Copy name and company" />}
        </div>
      ) : (
        <p className="mt-2 text-[15px] text-ink-muted">No contact in the ad</p>
      )}

      {(phone || email) && (
        <dl className="mt-3 divide-y divide-rule border-y border-rule">
          {phone && (
            <div className="flex items-center gap-4">
              <dt className="kicker w-14 shrink-0 text-ink-muted">Tel</dt>
              <dd className="flex min-w-0 flex-1 items-center justify-between gap-3">
                <a
                  href={telHref(phone)}
                  className="num flex min-h-11 flex-1 items-center text-[15px] text-blue underline-offset-4 hover:underline"
                >
                  {phone}
                </a>
                <CopyButton text={phone} label="Copy phone number" />
              </dd>
            </div>
          )}
          {email && (
            <div className="flex items-center gap-4">
              <dt className="kicker w-14 shrink-0 text-ink-muted">Email</dt>
              <dd className="min-w-0 flex-1">
                <a
                  href={`mailto:${email}`}
                  className="flex min-h-11 items-center truncate font-mono text-[13.5px] text-blue underline-offset-4 hover:underline"
                >
                  {email}
                </a>
              </dd>
            </div>
          )}
        </dl>
      )}

      <div className="mt-3 flex flex-col gap-1">
        {profile && (
          <div className="flex flex-wrap items-baseline gap-x-3">
            <ExtLink href={profile}>LinkedIn profile</ExtLink>
            <span className="text-[12.5px] text-ink-muted">likely match, check before inviting</span>
          </div>
        )}
        <div className="flex flex-wrap gap-x-5">
          <ExtLink href={search.linkedin}>Search LinkedIn</ExtLink>
          {search.google && <ExtLink href={search.google}>Search Google</ExtLink>}
        </div>
      </div>
      {jobId !== undefined && name && <RecruiterQuickLog jobId={jobId} />}
    </section>
  );
}

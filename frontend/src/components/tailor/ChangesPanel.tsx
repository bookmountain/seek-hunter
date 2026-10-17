import type { BulletChange, ChangeCounts, DiffOp, ProjectsChange, SkillsChange, SummaryChange, TailoringChange } from "@/lib/types";
import { wordDiff } from "@/lib/wordDiff";
import { cn } from "@/lib/utils";
import { RichText } from "./RichText";

function Kicker({ children }: { children: React.ReactNode }) {
  return <p className="kicker text-ink-muted">{children}</p>;
}

/**
 * Inline word diff: equal in ink, deletions grey + struck, insertions ink on faint blue.
 * Server diffs are word runs without the whitespace between runs, so a space is restored
 * wherever neither neighbour carries one (client-side diffs keep their own whitespace).
 */
export function DiffText({ ops }: { ops: DiffOp[] }) {
  return (
    <p className="text-[14px] leading-relaxed text-ink">
      {ops.map((o, i) => {
        const next = ops[i + 1];
        const sep = next && !/\s$/.test(o.text) && !/^\s/.test(next.text) ? " " : "";
        if (o.op === "equal")
          return (
            <span key={i}>
              {o.text}
              {sep}
            </span>
          );
        // keep surrounding spaces outside the mark so highlights hug the words
        const [, lead, core, trail] = /^(\s*)([\s\S]*?)(\s*)$/.exec(o.text) ?? ["", "", o.text, ""];
        return (
          <span key={i}>
            {lead}
            {o.op === "delete" ? (
              <del className="text-ink-muted decoration-ink-muted/80">{core}</del>
            ) : (
              <ins className="bg-mark px-px text-ink no-underline">{core}</ins>
            )}
            {trail}
            {sep}
          </span>
        );
      })}
    </p>
  );
}

const opsFor = (c: { diff?: DiffOp[]; before: string; after: string | null }) => c.diff ?? wordDiff(c.before, c.after ?? "");

/** The API sends 0-based positions within the role; show them 1-based. */
function movedLabel(b: BulletChange): string {
  const from = b.position_before;
  const to = b.position_after;
  if (from == null || to == null) return "Moved";
  return `Moved ${to < from ? "up" : "down"} ${from + 1} → ${to + 1}`;
}

/** One-line summary from `change_counts`, or counted from `changes` on older payloads. */
export function changeSummary(changes: TailoringChange[], counts?: ChangeCounts): string {
  const bullets = changes.filter((c): c is BulletChange => c.type === "bullet");
  const c: ChangeCounts = counts ?? {
    summary_changed: changes.some((x) => x.type === "summary" && x.changed),
    reworded: bullets.filter((b) => b.status === "reworded").length,
    removed: bullets.filter((b) => b.status === "removed").length,
    moved: bullets.filter((b) => b.status === "moved").length,
    skills_reordered: changes.filter((x) => x.type === "skills" && x.changed).length,
    projects_changed: changes.some((x) => x.type === "projects" && x.excluded.length > 0),
  };
  const parts: string[] = [];
  if (c.summary_changed) parts.push("Summary rewritten");
  if (c.reworded) parts.push(`${c.reworded} reworded`);
  if (c.removed) parts.push(`${c.removed} removed`);
  if (c.moved) parts.push(`${c.moved} moved`);
  if (c.skills_reordered) parts.push(`skills reordered in ${c.skills_reordered} ${c.skills_reordered === 1 ? "line" : "lines"}`);
  if (c.projects_changed) parts.push("projects changed");
  return parts.length ? parts.join(" · ") : "No changes";
}

function SummaryBlock({ c }: { c: SummaryChange }) {
  return (
    <section className="border-t border-rule pt-4">
      <Kicker>Summary</Kicker>
      {c.changed ? (
        <div className="mt-2">
          <DiffText ops={opsFor(c)} />
        </div>
      ) : (
        <p className="mt-2 text-[13px] text-ink-muted">Unchanged</p>
      )}
    </section>
  );
}

function BulletGroup({ company, bullets }: { company: string; bullets: BulletChange[] }) {
  const changed = bullets.filter((b) => b.status !== "kept");
  const kept = bullets.filter((b) => b.status === "kept");
  return (
    <div className="border-t border-rule pt-3">
      <p className="font-display text-[15px] font-semibold tracking-[-0.01em]">{company}</p>
      <ul className="mt-2 space-y-3">
        {changed.map((b) =>
          b.status === "removed" ? (
            <li key={b.id} className="text-[14px] leading-relaxed text-ink-muted">
              <span className="kicker mr-2 bg-chip px-1.5 py-[2px] text-[10px] text-ink">Removed</span>
              <RichText text={b.before} />
            </li>
          ) : (
            <li key={b.id} className="space-y-1">
              {b.status === "moved" && (
                <span className="kicker inline-block border border-ink px-1.5 py-[2px] text-[10px] text-ink">{movedLabel(b)}</span>
              )}
              {b.status === "moved" && (b.after === null || b.after === b.before) && !b.diff?.some((o) => o.op !== "equal") ? (
                <p className="text-[14px] leading-relaxed text-ink">
                  <RichText text={b.before} />
                </p>
              ) : (
                <DiffText ops={opsFor(b)} />
              )}
            </li>
          ),
        )}
      </ul>
      {kept.length > 0 && (
        <details className="group mt-2">
          <summary className="kicker cursor-pointer list-none py-1 text-ink-muted hover:text-blue">
            <span className="mr-1 inline-block transition-transform group-open:rotate-90" aria-hidden>
              ›
            </span>
            {kept.length} unchanged
          </summary>
          <ul className="mt-1 space-y-1.5 border-l border-rule pl-3">
            {kept.map((b) => (
              <li key={b.id} className="text-[13px] leading-relaxed text-ink-muted">
                <RichText text={b.before} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function SkillLine({ c }: { c: SkillsChange }) {
  const removed = c.before.filter((s) => !c.after.includes(s));
  return (
    <div className="py-2">
      <p className="text-[12.5px] font-medium">{c.category}</p>
      {c.changed ? (
        <>
          <p className="mt-1 font-mono text-[11.5px] leading-relaxed text-ink-muted">
            {c.before.map((s, i) => (
              <span key={s}>
                {i > 0 && ", "}
                <span className={cn(removed.includes(s) && "line-through")}>{s}</span>
              </span>
            ))}
          </p>
          <p className="mt-0.5 font-mono text-[11.5px] leading-relaxed text-ink">
            <span className="text-ink-muted" aria-label="becomes">
              →{" "}
            </span>
            {c.after.map((s, i) => (
              <span key={s}>
                {i > 0 && ", "}
                <span className={cn(c.before[i] !== s && "bg-mark px-0.5")}>{s}</span>
              </span>
            ))}
          </p>
        </>
      ) : (
        <p className="mt-1 font-mono text-[11.5px] leading-relaxed text-ink-muted">{c.before.join(", ")} · unchanged</p>
      )}
    </div>
  );
}

function ProjectsBlock({ c }: { c: ProjectsChange }) {
  return (
    <section className="border-t border-rule pt-4">
      <Kicker>Projects</Kicker>
      <ul className="mt-2 space-y-1 text-[14px]">
        {c.included.map((p) => (
          <li key={p}>{p}</li>
        ))}
        {c.excluded.map((p) => (
          <li key={p} className="text-ink-muted">
            <del>{p}</del> <span className="kicker ml-1 bg-chip px-1.5 py-[2px] text-[10px] text-ink">Left out</span>
          </li>
        ))}
        {!c.included.length && !c.excluded.length && <li className="text-ink-muted">None</li>}
      </ul>
    </section>
  );
}

/** Human-readable diff of what the tailoring changed. */
export function ChangesPanel({ changes, counts }: { changes: TailoringChange[]; counts?: ChangeCounts }) {
  const summary = changes.find((c): c is SummaryChange => c.type === "summary");
  const bullets = changes.filter((c): c is BulletChange => c.type === "bullet");
  const skills = changes.filter((c): c is SkillsChange => c.type === "skills");
  const projects = changes.find((c): c is ProjectsChange => c.type === "projects");

  const groups: { company: string; bullets: BulletChange[] }[] = [];
  for (const b of bullets) {
    const g = groups.find((x) => x.company === b.company);
    if (g) g.bullets.push(b);
    else groups.push({ company: b.company, bullets: [b] });
  }

  return (
    <div aria-label="Changes" role="region" className="space-y-5">
      <div className="border-b-2 border-ink pb-2">
        <h2 className="kicker text-ink">Changes</h2>
        <p data-testid="change-summary" className="mt-1 font-mono text-[11.5px] leading-snug text-ink-muted">
          {changeSummary(changes, counts)}
        </p>
      </div>
      {summary && <SummaryBlock c={summary} />}
      {groups.length > 0 && (
        <section>
          <Kicker>Experience</Kicker>
          <div className="mt-2 space-y-4">
            {groups.map((g) => (
              <BulletGroup key={g.company} company={g.company} bullets={g.bullets} />
            ))}
          </div>
        </section>
      )}
      {skills.length > 0 && (
        <section className="border-t border-rule pt-4">
          <Kicker>Skills order</Kicker>
          <div className="mt-1 divide-y divide-rule">
            {skills.map((s) => (
              <SkillLine key={s.id} c={s} />
            ))}
          </div>
        </section>
      )}
      {projects && <ProjectsBlock c={projects} />}
    </div>
  );
}

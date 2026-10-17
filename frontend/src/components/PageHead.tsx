import type { ReactNode } from "react";

/** Section masthead for the secondary pages: kicker, grotesk title, optional dek and actions. */
export function PageHead({ kicker, title, dek, actions }: { kicker: string; title: string; dek?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4 border-b-2 border-ink pb-5">
      <div className="max-w-2xl">
        <p className="kicker text-ink-muted">{kicker}</p>
        <h1
          className="display mt-2 text-[44px] leading-none"
        >
          {title}
        </h1>
        {dek && <p className="mt-3 text-[15px] leading-relaxed text-ink-muted">{dek}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

export function Page({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return <div className={`mx-auto w-full ${wide ? "max-w-7xl" : "max-w-6xl"} px-5 py-8 lg:px-8 lg:py-10`}>{children}</div>;
}

/** Bold grotesk section heading with an ink rule beneath. */
export function SectionHead({ children }: { children: ReactNode }) {
  return (
    <h2
      className="display border-b border-ink pb-2 text-[20px] leading-tight"
    >
      {children}
    </h2>
  );
}

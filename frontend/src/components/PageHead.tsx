import type { ReactNode } from "react";

/** Section masthead for the secondary pages: kicker, serif title, optional dek and actions. */
export function PageHead({ kicker, title, dek, actions }: { kicker: string; title: string; dek?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4 border-b border-ink pb-5">
      <div className="max-w-2xl">
        <p className="kicker text-signal">{kicker}</p>
        <h1
          className="display mt-2 text-[40px] leading-none font-semibold tracking-[-0.02em]"
          style={{ fontVariationSettings: '"opsz" 144, "SOFT" 30, "WONK" 0' }}
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

/** Small serif section heading with a hairline beneath. */
export function SectionHead({ children }: { children: ReactNode }) {
  return (
    <h2
      className="display border-b border-rule pb-2 text-[22px] leading-tight font-medium italic"
      style={{ fontVariationSettings: '"opsz" 48, "SOFT" 60, "WONK" 0' }}
    >
      {children}
    </h2>
  );
}

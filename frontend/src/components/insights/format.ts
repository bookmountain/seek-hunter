import type { City } from "@/lib/types";

export const CITIES: City[] = ["adelaide", "melbourne", "sydney", "perth"];

export const CITY_LABEL: Record<City, string> = {
  adelaide: "Adelaide",
  melbourne: "Melbourne",
  sydney: "Sydney",
  perth: "Perth",
};

export const ROLE_FAMILIES = ["frontend", "backend", "fullstack", "ai_ml", "data", "devops_cloud", "mobile", "qa", "it_support"];

const ROLE_LABEL: Record<string, string> = {
  frontend: "Frontend",
  backend: "Backend",
  fullstack: "Full stack",
  ai_ml: "AI / ML",
  data: "Data",
  devops_cloud: "DevOps / cloud",
  mobile: "Mobile",
  qa: "QA / test",
  it_support: "IT support",
  other: "Other",
};

export const roleLabel = (f: string) => ROLE_LABEL[f] ?? f;

/** 0–1 share as a whole percent; tiny non-zero values read "<1%". */
export function pct(share: number): string {
  if (share > 0 && share < 0.005) return "<1%";
  return `${Math.round(share * 100)}%`;
}

export const money = (v: number | null) => (v === null ? "—" : `$${Math.round(v)}`);

/** A "nice" axis maximum for shares, in 5% / 10% steps. */
export function niceShareMax(max: number): number {
  if (max <= 0) return 0.1;
  const step = max <= 0.3 ? 0.05 : 0.1;
  return Math.min(1, Math.ceil((max + 0.0001) / step) * step);
}

/** Series encodings for up to three compared skills: ink circle, blue square, grey diamond. */
export const SERIES = [
  { color: "var(--ink)", shape: "circle" as const, name: "ink" },
  { color: "var(--blue)", shape: "square" as const, name: "blue" },
  { color: "var(--ink-low)", shape: "diamond" as const, name: "grey" },
];

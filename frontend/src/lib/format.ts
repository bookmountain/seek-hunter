import type { Job, WorkType } from "./types";
import { parseIsoUtc } from "./utils";

/** Compact age, e.g. "5h", "3d". */
export function since(iso: string, now = Date.now()): string {
  const h = Math.max(0, Math.round((now - parseIsoUtc(iso).getTime()) / 3_600_000));
  return h < 24 ? `${h}h` : `${Math.round(h / 24)}d`;
}

export const FLEXIBLE_TYPES: ReadonlySet<WorkType> = new Set(["part_time", "contract", "casual"]);

export const isFlexible = (j: Pick<Job, "work_type">) => FLEXIBLE_TYPES.has(j.work_type);

export const WORK_TYPE_CAPS: Record<WorkType, string> = {
  full_time: "Full-time",
  part_time: "Part-time",
  contract: "Contract",
  casual: "Casual",
  unknown: "Type n/a",
};

export const CITY_NAME: Record<string, string> = {
  adelaide: "Adelaide",
  melbourne: "Melbourne",
  sydney: "Sydney",
  perth: "Perth",
  brisbane: "Brisbane",
  other: "Other",
};

export const cityName = (c: string | null | undefined) => (c ? (CITY_NAME[c] ?? c) : "");

export const sourceName = (s: Job["source"]) => (s === "seek" ? "SEEK" : "Jora");

/** Relative age for status lines, e.g. "just now", "12m ago", "2h ago", "3d ago". */
export function ago(iso: string, now = Date.now()): string {
  const m = Math.max(0, Math.round((now - parseIsoUtc(iso).getTime()) / 60_000));
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  return h < 24 ? `${h}h ago` : `${Math.round(h / 24)}d ago`;
}

/** Adelaide wall-clock time, e.g. "17 Oct, 14:02". */
export function adelaideTime(iso: string): string {
  return parseIsoUtc(iso).toLocaleString("en-AU", {
    timeZone: "Australia/Adelaide",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

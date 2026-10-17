export { cn } from "cn"

const HAS_TZ = /[zZ]|[+-]\d\d:?\d\d$/;

/** Backend timestamps are naive UTC; only append "Z" when no timezone is already present. */
export function parseIsoUtc(iso: string): Date {
  return new Date(HAS_TZ.test(iso) ? iso : `${iso}Z`);
}

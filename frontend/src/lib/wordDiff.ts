import type { DiffOp } from "./types";

const MAX_CELLS = 250_000;

/** Splits into words and the whitespace between them, so joining the tokens restores the text. */
const tokenize = (s: string) => s.split(/(\s+)/).filter((t) => t.length > 0);

/** Word-level diff (LCS over whitespace tokens), merged into runs. Used when the API sends no `diff`. */
export function wordDiff(before: string, after: string): DiffOp[] {
  if (before === after) return before ? [{ op: "equal", text: before }] : [];
  const a = tokenize(before);
  const b = tokenize(after);
  if (a.length * b.length > MAX_CELLS) {
    return [
      ...(before ? [{ op: "delete" as const, text: before }] : []),
      ...(after ? [{ op: "insert" as const, text: after }] : []),
    ];
  }
  // lcs[i][j] = LCS length of a[i:] and b[j:]
  const lcs: Uint16Array[] = Array.from({ length: a.length + 1 }, () => new Uint16Array(b.length + 1));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const out: DiffOp[] = [];
  const push = (op: DiffOp["op"], text: string) => {
    const last = out[out.length - 1];
    if (last && last.op === op) last.text += text;
    else out.push({ op, text });
  };
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      push("equal", a[i]);
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      push("delete", a[i++]);
    } else {
      push("insert", b[j++]);
    }
  }
  while (i < a.length) push("delete", a[i++]);
  while (j < b.length) push("insert", b[j++]);
  return tidy(out);
}

/**
 * Whitespace-only equal runs sandwiched between changes read as noise ("del␣ins␣del␣ins");
 * fold each such stretch into one delete phrase followed by one insert phrase.
 */
function tidy(ops: DiffOp[]): DiffOp[] {
  const res: DiffOp[] = [];
  let del = "";
  let ins = "";
  let ws = "";
  const flush = () => {
    if (del) res.push({ op: "delete", text: del });
    if (ins) res.push({ op: "insert", text: ins });
    del = ins = "";
    if (ws) res.push({ op: "equal", text: ws });
    ws = "";
  };
  ops.forEach((op, k) => {
    const inGroup = del !== "" || ins !== "";
    if (op.op === "equal") {
      const next = ops[k + 1];
      if (inGroup && /^\s+$/.test(op.text) && next && next.op !== "equal") {
        ws = op.text;
        return;
      }
      flush();
      const last = res[res.length - 1];
      if (last?.op === "equal") last.text += op.text;
      else res.push({ ...op });
      return;
    }
    if (ws) {
      if (del) del += ws;
      if (ins) ins += ws;
      ws = "";
    }
    if (op.op === "delete") del += op.text;
    else ins += op.text;
  });
  flush();
  return res;
}

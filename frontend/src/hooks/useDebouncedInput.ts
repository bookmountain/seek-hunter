import { useEffect, useRef, useState } from "react";

/**
 * A text box bound to a URL-backed value: typing commits after `delay` ms, and outside changes
 * to the value (saved prefs applied, reset) flow back into the box.
 */
export function useDebouncedInput(value: string, commit: (v: string) => void, delay = 250) {
  const [text, setText] = useState(value);
  useEffect(() => {
    if (text.trim() === value) return;
    const t = setTimeout(() => commit(text.trim()), delay);
    return () => clearTimeout(t);
  }, [text, value, commit, delay]);
  const last = useRef(value);
  useEffect(() => {
    if (value !== last.current) {
      last.current = value;
      setText(value);
    }
  }, [value]);
  return [text, setText] as const;
}

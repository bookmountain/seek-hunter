import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";

export type Filters = Record<string, string>;

const PREFS_KEY = ["ui-prefs"];
const SAVE_DELAY = 500;

const normalize = (raw: Record<string, unknown> | undefined, defaults: Filters): Filters =>
  Object.fromEntries(
    Object.keys(defaults).map((k) => {
      const v = raw?.[k];
      return [k, typeof v === "string" ? v : typeof v === "number" ? String(v) : defaults[k]];
    }),
  );

/**
 * Page filters that live in the URL (the source of truth while on the page) and are remembered
 * server-side per page, so they follow the user across devices.
 *
 * - On mount, if the URL has none of this page's filter params, the saved prefs are written into
 *   the URL (replace).
 * - Any later change is PUT to /api/ui-prefs/{page}, debounced 500 ms.
 * - Params outside `defaults` (e.g. `job`, `run`) are never touched or persisted.
 */
export function usePersistedFilters(page: string, defaults: Filters) {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const keys = useMemo(() => Object.keys(defaults), [defaults]);
  const values: Filters = Object.fromEntries(keys.map((k) => [k, params.get(k) ?? defaults[k]]));
  const json = JSON.stringify(values);

  // Decided once, at mount: does the URL already say what to show?
  const [urlHadFilters] = useState(() => keys.some((k) => params.has(k)));
  const [ready, setReady] = useState(urlHadFilters);
  // What the server already has (or what we just loaded from it) - skip saving that again.
  const [initialSaved] = useState<string | null>(() => (urlHadFilters ? json : null));
  const lastSaved = useRef<string | null>(initialSaved);

  const prefs = useQuery({ queryKey: PREFS_KEY, queryFn: api.uiPrefs, staleTime: 60_000, retry: false, enabled: !ready });

  const set = useCallback(
    (patch: Filters) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch)) {
            if (!(k in defaults)) continue;
            if (v === "" || v === defaults[k]) next.delete(k);
            else next.set(k, v);
          }
          return next;
        },
        { replace: true },
      ),
    [setParams, defaults],
  );

  const save = useCallback(
    (f: Filters) => {
      lastSaved.current = JSON.stringify(f);
      qc.setQueryData(PREFS_KEY, (old: Record<string, unknown> | undefined) => ({ ...(old ?? {}), [page]: f }));
      api.putUiPrefs(page, f).catch(() => {
        // best effort: the URL still holds the filters
      });
    },
    [qc, page],
  );

  // Apply saved prefs once they load (only when the URL had no filters of its own).
  useEffect(() => {
    if (ready) return;
    if (prefs.data) {
      const saved = normalize(prefs.data[page] as Record<string, unknown> | undefined, defaults);
      set(saved);
      lastSaved.current = JSON.stringify(saved);
      setReady(true);
    } else if (prefs.isError) {
      setReady(true);
    }
  }, [ready, prefs.data, prefs.isError, page, defaults, set]);

  // Debounced save on change.
  useEffect(() => {
    if (!ready || lastSaved.current === json) return;
    const t = setTimeout(() => save(JSON.parse(json) as Filters), SAVE_DELAY);
    return () => clearTimeout(t);
  }, [json, ready, save]);

  const reset = useCallback(() => {
    set(defaults);
    save({ ...defaults });
  }, [set, save, defaults]);

  const isDefault = keys.every((k) => values[k] === defaults[k]);

  return { values, set, reset, ready, isDefault };
}

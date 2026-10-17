/** Small text button that clears a page's filters back to defaults (and saves that). */
export function ResetFilters({ onReset, disabled }: { onReset: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      onClick={onReset}
      disabled={disabled}
      className="kicker text-[10.5px] text-blue hover:underline disabled:text-ink-faint disabled:no-underline"
    >
      Reset filters
    </button>
  );
}

import { Toaster as Sonner, type ToasterProps } from "sonner"

/** Toasts as small printed slips: paper, ink border, mono text, no icons. */
const Toaster = ({ ...props }: ToasterProps) => (
  <Sonner
    theme="light"
    position="bottom-left"
    className="toaster group"
    icons={{ success: null, info: null, warning: null, error: null }}
    style={
      {
        "--normal-bg": "var(--paper-lift)",
        "--normal-text": "var(--ink)",
        "--normal-border": "var(--ink)",
        "--border-radius": "0px",
      } as React.CSSProperties
    }
    toastOptions={{
      classNames: {
        toast: "!font-mono !text-[12px] !tracking-[0.04em] !shadow-[3px_3px_0_0_rgb(22_20_18/0.12)]",
        error: "!text-signal !border-signal",
      },
    }}
    {...props}
  />
)

export { Toaster }

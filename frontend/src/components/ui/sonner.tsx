import { Toaster as Sonner, type ToasterProps } from "sonner"

/** Toasts: white, ink border, mono text, no icons. */
const Toaster = ({ ...props }: ToasterProps) => (
  <Sonner
    theme="light"
    position="bottom-left"
    className="toaster group"
    icons={{ success: null, info: null, warning: null, error: null }}
    style={
      {
        "--normal-bg": "#ffffff",
        "--normal-text": "var(--ink)",
        "--normal-border": "var(--ink)",
        "--border-radius": "0px",
      } as React.CSSProperties
    }
    toastOptions={{
      classNames: {
        toast: "!font-mono !text-[12px] !tracking-[0.04em] !shadow-none",
        error: "!text-ink !border-ink !border-l-4",
      },
    }}
    {...props}
  />
)

export { Toaster }

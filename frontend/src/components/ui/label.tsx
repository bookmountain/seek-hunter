import * as React from "react"
import { cn } from "cn"

function Label({ className, ...props }: React.ComponentProps<"label">) {
  return (
    <label
      data-slot="label"
      className={cn("kicker flex items-center gap-2 text-ink-muted select-none", className)}
      {...props}
    />
  )
}

export { Label }

import { Switch as SwitchPrimitive } from "@base-ui/react/switch"
import { cn } from "cn"

/** A square, hairline toggle: an ink block slides across a ruled track. */
function Switch({ className, ...props }: SwitchPrimitive.Root.Props) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        "group/switch relative inline-flex h-[18px] w-[34px] shrink-0 items-center rounded-none border border-rule-strong bg-transparent p-[2px] transition-colors outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue data-checked:border-blue data-checked:bg-blue data-disabled:cursor-not-allowed data-disabled:opacity-50",
        className
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className="pointer-events-none block size-3 bg-ink transition-transform data-checked:translate-x-4 data-checked:bg-white"
      />
    </SwitchPrimitive.Root>
  )
}

export { Switch }

import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-none border font-mono text-[12px] font-medium tracking-[0.08em] uppercase whitespace-nowrap transition-colors outline-none select-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal disabled:pointer-events-none disabled:opacity-40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
  {
    variants: {
      variant: {
        default: "border-ink bg-ink text-paper hover:bg-ink/85",
        outline: "border-rule-strong bg-transparent text-ink hover:bg-ink/[0.05] hover:border-ink",
        secondary: "border-rule bg-paper-deep text-ink hover:border-rule-strong",
        ghost: "border-transparent bg-transparent text-ink-muted hover:text-ink hover:bg-ink/[0.05]",
        destructive: "border-signal/60 bg-transparent text-signal hover:bg-signal/[0.07]",
        link: "border-transparent px-0 normal-case tracking-normal font-sans text-sm text-ink underline decoration-rule-strong underline-offset-4 hover:decoration-ink",
      },
      size: {
        default: "h-9 px-3.5",
        xs: "h-6 px-2 text-[10.5px]",
        sm: "h-8 px-3 text-[11px]",
        lg: "h-10 px-4",
        icon: "size-9",
        "icon-xs": "size-6",
        "icon-sm": "size-8",
        "icon-lg": "size-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }

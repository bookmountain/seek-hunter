import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-none border font-mono text-[12px] font-medium tracking-[0.08em] uppercase whitespace-nowrap transition-colors outline-none select-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue disabled:pointer-events-none disabled:opacity-40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
  {
    variants: {
      variant: {
        default: "border-ink bg-ink text-white hover:border-blue hover:bg-blue focus-visible:border-blue focus-visible:bg-blue",
        outline: "border-ink bg-transparent text-ink hover:border-blue hover:text-blue",
        secondary: "border-chip bg-chip text-ink hover:border-ink",
        ghost: "border-transparent bg-transparent text-ink-muted hover:text-blue",
        destructive: "border-ink bg-transparent text-ink hover:bg-chip",
        link: "border-transparent px-0 normal-case tracking-normal font-sans text-sm text-blue underline underline-offset-4 hover:decoration-2",
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

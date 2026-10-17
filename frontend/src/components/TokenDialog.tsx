import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { getToken, setToken } from "@/lib/api";
import { cn } from "@/lib/utils";

export function TokenDialog() {
  const [value, setValue] = useState(getToken());
  const [open, setOpen] = useState(false);
  const hasToken = !!getToken();
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        className={cn(
          "kicker inline-flex items-center gap-2 py-1 underline-offset-[5px] hover:underline",
          hasToken ? "text-ink-muted" : "text-blue",
        )}
      >
        <span aria-hidden className={cn("size-[7px]", hasToken ? "bg-ink" : "border border-blue")} />
        {hasToken ? "Token set" : "Set write token"}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Write token</DialogTitle>
          <DialogDescription>
            Needed to change statuses, searches and settings. Find it as{" "}
            <code className="font-mono text-[12px] text-ink">API_WRITE_TOKEN</code> in{" "}
            <code className="font-mono text-[12px] text-ink">/opt/seek-hunter/.env</code>.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            setToken(value.trim());
            setOpen(false);
          }}
        >
          <Input type="password" aria-label="Write token" value={value} onChange={(e) => setValue(e.target.value)} />
          <Button type="submit">Save token</Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

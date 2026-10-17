import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { getToken, setToken } from "@/lib/api";

export function TokenDialog() {
  const [value, setValue] = useState(getToken());
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button variant={getToken() ? "ghost" : "outline"} size="sm" />}>
        {getToken() ? "🔑 Token set" : "Set write token"}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Write token</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">
          Needed to change statuses, searches and settings. Find it as API_WRITE_TOKEN in /opt/seek-hunter/.env.
        </p>
        <Input type="password" value={value} onChange={(e) => setValue(e.target.value)} />
        <Button
          onClick={() => {
            setToken(value.trim());
            setOpen(false);
          }}
        >
          Save
        </Button>
      </DialogContent>
    </Dialog>
  );
}

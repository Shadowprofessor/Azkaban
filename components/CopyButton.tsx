"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch {
          /* clipboard blocked: user can still select the text */
        }
      }}
      className="inline-flex items-center gap-1.5 rounded-md border border-border bg-raised px-2.5 py-1 text-xs hover:bg-border"
    >
      {done ? <Check size={13} className="text-success" aria-hidden /> : <Copy size={13} aria-hidden />}
      {done ? "Copied" : label}
    </button>
  );
}

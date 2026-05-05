"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";

type NavItem = { href: string; label: string };

export function MobileNav({ items }: { items: NavItem[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="md:hidden">
      <button
        type="button"
        aria-label="Open navigation"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="rounded-md border border-border/60 px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        {open ? "Close" : "Menu"}
      </button>
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
          onClick={() => setOpen(false)}
        >
          <nav
            className={cn(
              "absolute right-0 top-0 h-full w-64 border-l border-border/60 bg-card",
              "flex flex-col gap-1 p-4",
            )}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-2 text-[10px] uppercase tracking-wider text-muted-foreground">
              Navigation
            </div>
            {items.map((n) => (
              <a
                key={n.href}
                className="rounded-md px-3 py-2 text-sm hover:bg-muted"
                href={n.href}
                onClick={() => setOpen(false)}
              >
                {n.label}
              </a>
            ))}
          </nav>
        </div>
      )}
    </div>
  );
}

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, BarChart3, FlaskConical, Grid3x3, Home, ListTree, Search } from "lucide-react";

import { cn } from "@/lib/utils";

const NAV = [
  { href: "/",        label: "Overview",         icon: Home },
  { href: "/sleeves", label: "Sleeves",          icon: ListTree },
  { href: "/matrix",  label: "Matrix",           icon: Grid3x3 },
  { href: "/trades",  label: "Trade Explorer",   icon: Search },
  { href: "/failures", label: "Failure Analysis", icon: BarChart3 },
  { href: "/lab",     label: "Strategy Lab",     icon: FlaskConical },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="flex h-full w-56 shrink-0 flex-col border-r border-border/60 bg-card/40 px-3 py-6">
      <Link href="/" className="mb-6 flex items-center gap-2 px-2">
        <Activity className="h-5 w-5 text-foreground/80" />
        <div className="flex flex-col leading-tight">
          <span className="text-sm font-semibold tracking-tight">Paper Trade</span>
          <span className="text-[11px] text-muted-foreground">Master Lab</span>
        </div>
      </Link>

      <nav className="flex flex-col gap-0.5">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/40 hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto px-3 text-[10px] text-muted-foreground">
        <div>v0.3.0 · Phase 3</div>
        <div>−22% realism haircut</div>
      </div>
    </aside>
  );
}

"use client";

import { useApi } from "@/lib/api";
import { cn } from "@/lib/utils";

type Criterion = {
  name: string;
  passed: boolean;
  actual: string | number | null;
  required: string | number | null;
  detail: string | null;
};

type Eval = {
  sleeve_id: string;
  current_mode: string;
  next_mode: string | null;
  eligible: boolean;
  criteria: Criterion[];
  kill_criteria: Criterion[];
  kill_triggered: boolean;
  notes: string[];
};

const MODE_ORDER = ["replay_only", "live_log", "live_signal", "live_full"];

const MODE_COLOR: Record<string, string> = {
  replay_only:  "bg-muted/60 text-muted-foreground border-border/40",
  live_log:     "bg-amber-400/15 text-amber-400 border-amber-400/20",
  live_signal:  "bg-sky-500/15 text-sky-400 border-sky-500/20",
  live_full:    "bg-profit/15 text-profit border-profit/20",
};

export function PromotionPanel({ sleeveId }: { sleeveId: string }) {
  const { data, error, isLoading } = useApi<Eval>(
    `/promotion/check?sleeve_id=${encodeURIComponent(sleeveId)}`,
    60_000,
  );

  if (isLoading) {
    return (
      <div className="rounded-xl border border-border/60 bg-card px-5 py-4 text-sm text-muted-foreground">
        Evaluating promotion gates…
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="rounded-xl border border-loss/30 bg-loss/10 px-5 py-4 text-sm text-loss">
        Promotion check unavailable.
      </div>
    );
  }

  const isTop = data.current_mode === "live_full";
  const currentIdx = MODE_ORDER.indexOf(data.current_mode);

  return (
    <div className="space-y-5 rounded-xl border border-border/60 bg-card p-5">

      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/60">Promotion Status</div>
          {data.next_mode && (
            <div className="mt-1 text-xs text-muted-foreground">
              Ready to advance:{" "}
              <span className={cn("font-semibold", data.eligible ? "text-profit" : "text-muted-foreground")}>
                {data.eligible ? "yes" : "not yet"}
              </span>
            </div>
          )}
        </div>
        {isTop && (
          <div className="flex items-center gap-1.5 rounded-full border border-profit/25 bg-profit/10 px-2.5 py-1">
            <span className="h-1.5 w-1.5 rounded-full bg-profit" style={{ animation: "pulse-dot 2s ease-in-out infinite" }} />
            <span className="text-[10px] font-bold uppercase tracking-widest text-profit">live full</span>
          </div>
        )}
      </div>

      {/* Mode ladder */}
      <div className="flex flex-wrap items-center gap-1.5">
        {MODE_ORDER.map((m, i) => {
          const active = m === data.current_mode;
          const past = currentIdx > i;
          return (
            <div key={m} className="flex items-center gap-1.5">
              <span className={cn(
                "rounded-full border px-2.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wide transition-colors",
                active
                  ? (MODE_COLOR[m] ?? "bg-muted text-muted-foreground border-border/40")
                  : past
                  ? "border-border/30 bg-muted/40 text-muted-foreground/50"
                  : "border-border/40 bg-card text-muted-foreground/40",
              )}>
                {m}
              </span>
              {i < MODE_ORDER.length - 1 && (
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none" className="shrink-0 text-muted-foreground/30" aria-hidden="true">
                  <path d="M2 5h6M5 2l3 3-3 3" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </div>
          );
        })}
      </div>

      {/* Criteria */}
      {!isTop && data.next_mode && (
        <CriteriaList
          title={`Gate: ${data.current_mode} → ${data.next_mode}`}
          criteria={data.criteria}
        />
      )}

      {isTop && (
        <CriteriaList
          title="Kill criteria (live_full)"
          criteria={data.kill_criteria}
          isKill={data.kill_triggered}
        />
      )}

      {/* Notes */}
      {data.notes.length > 0 && (
        <ul className="space-y-1 border-t border-border/40 pt-4">
          {data.notes.map((n) => (
            <li key={n} className="flex items-start gap-2 text-xs text-muted-foreground">
              <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-muted-foreground/40" />
              {n}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CriteriaList({
  title, criteria, isKill,
}: { title: string; criteria: Criterion[]; isKill?: boolean }) {
  if (criteria.length === 0) {
    return (
      <div className="text-xs text-muted-foreground/60">No criteria configured for this gate.</div>
    );
  }
  return (
    <div className="space-y-2.5">
      <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/60">
        {title}
        {isKill && (
          <span className="ml-2 rounded-full border border-loss/30 bg-loss/10 px-1.5 py-0.5 text-loss">
            triggered
          </span>
        )}
      </div>
      <div className="space-y-1.5">
        {criteria.map((c) => {
          const ok = c.passed;
          return (
            <div
              key={c.name}
              className={cn(
                "flex items-center justify-between gap-3 rounded-xl border px-3 py-2 text-xs transition-colors",
                ok
                  ? "border-profit/15 bg-profit/5"
                  : "border-loss/15 bg-loss/5",
              )}
            >
              <div className="flex items-center gap-2">
                <span className={cn("inline-block h-1.5 w-1.5 shrink-0 rounded-full", ok ? "bg-profit" : "bg-loss")} />
                <span className="font-mono text-foreground">{c.name}</span>
              </div>
              <div className="flex items-center gap-3 font-mono text-muted-foreground">
                <span className={cn("font-semibold", ok ? "text-profit" : "text-loss")}>
                  {String(c.actual ?? "—")}
                </span>
                <span className="text-muted-foreground/40">vs</span>
                <span>{String(c.required ?? "—")}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

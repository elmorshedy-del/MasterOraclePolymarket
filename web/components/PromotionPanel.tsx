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

export function PromotionPanel({ sleeveId }: { sleeveId: string }) {
  const { data, error, isLoading } = useApi<Eval>(
    `/promotion/check?sleeve_id=${encodeURIComponent(sleeveId)}`,
    60_000,
  );

  if (isLoading) return <div className="text-sm text-muted-foreground">Evaluating gates…</div>;
  if (error || !data) return <div className="text-sm text-loss">Promotion check unavailable.</div>;

  const isTop = data.current_mode === "live_full";

  return (
    <div className="space-y-4 rounded-lg border border-border/60 bg-card p-5">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-medium text-muted-foreground">Promotion Status</h3>
        {data.next_mode && (
          <div className="text-xs text-muted-foreground">
            Eligible to advance:{" "}
            <span className={cn(data.eligible ? "text-profit" : "text-muted-foreground")}>
              {data.eligible ? "yes" : "not yet"}
            </span>
          </div>
        )}
      </div>

      <ModeLadder current={data.current_mode} />

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

      {data.notes.length > 0 && (
        <ul className="text-xs text-muted-foreground">
          {data.notes.map((n) => <li key={n}>· {n}</li>)}
        </ul>
      )}
    </div>
  );
}

function ModeLadder({ current }: { current: string }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      {MODE_ORDER.map((m, i) => {
        const active = m === current;
        const past = MODE_ORDER.indexOf(current) > i;
        return (
          <div key={m} className="flex items-center gap-2">
            <span
              className={cn(
                "rounded px-2 py-0.5 font-mono text-[11px]",
                active ? "bg-profit/20 text-profit" :
                past ? "bg-muted text-muted-foreground" : "bg-card text-muted-foreground border border-border/60",
              )}
            >
              {m}
            </span>
            {i < MODE_ORDER.length - 1 && (
              <span className="text-muted-foreground">→</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

function CriteriaList({
  title, criteria, isKill,
}: { title: string; criteria: Criterion[]; isKill?: boolean }) {
  if (criteria.length === 0) {
    return (
      <div className="text-xs text-muted-foreground">No criteria configured for this gate.</div>
    );
  }
  return (
    <div className="space-y-2">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{title}</div>
      <div className="space-y-1.5">
        {criteria.map((c) => {
          const ok = c.passed;
          const tone = isKill ? (ok ? "text-profit" : "text-loss") : (ok ? "text-profit" : "text-loss");
          return (
            <div key={c.name} className="flex items-center justify-between gap-3 rounded-md border border-border/40 bg-card/40 px-3 py-1.5 text-xs">
              <div className="flex items-center gap-2">
                <span className={cn("inline-block h-1.5 w-1.5 rounded-full", ok ? "bg-profit" : "bg-loss")} />
                <span className="font-mono">{c.name}</span>
              </div>
              <div className="flex items-center gap-3 text-muted-foreground">
                <span className="font-mono text-foreground">{String(c.actual ?? "—")}</span>
                <span>vs</span>
                <span className="font-mono">{String(c.required ?? "—")}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

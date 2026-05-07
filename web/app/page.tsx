import { SleevesTable } from "@/components/SleevesTable";
import { SystemHealth } from "@/components/SystemHealth";
import { cn } from "@/lib/utils";

export default function OverviewPage() {
  return (
    <div className="grid grid-cols-1 gap-10 lg:grid-cols-[1fr_288px]">
      {/* Main column */}
      <div className="space-y-10">

        {/* ── Hero ─────────────────────────────────────────────── */}
        <section className="space-y-4">
          <LiveBadge />
          <div>
            <h1 className="text-[2rem] font-bold tracking-tight">Overview</h1>
            <p className="mt-2 max-w-lg text-sm leading-relaxed text-muted-foreground">
              Fill simulator and position tracker online. Add a sleeve YAML to start
              running your first strategy.
            </p>
          </div>
        </section>

        {/* ── KPI Grid ─────────────────────────────────────────── */}
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="Total P&L"
            sublabel="after −22% haircut"
            value="—"
            sub="awaiting first sleeve"
            accent="profit"
          />
          <MetricCard
            label="Active Sleeves"
            sublabel="running strategies"
            value="0"
            sub="0 in live_full"
            accent="highlight"
          />
          <MetricCard
            label="Trades Today"
            sublabel="all modes"
            value="0"
            sub="no fills yet"
            accent="sky"
          />
          <MetricCard
            label="Ingestion"
            sublabel="data pipeline"
            value="live"
            sub="system nominal"
            accent="amber"
          />
        </section>

        {/* ── Sleeves ──────────────────────────────────────────── */}
        <section className="space-y-4">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-base font-semibold tracking-tight">Sleeves</h2>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Running strategy instances
              </p>
            </div>
            <a
              href="/sleeves"
              className="mt-0.5 cursor-pointer text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              View all →
            </a>
          </div>
          <SleevesTable />
        </section>

        {/* ── Roadmap ──────────────────────────────────────────── */}
        <section className="space-y-5">
          <div>
            <h2 className="text-base font-semibold tracking-tight">Status</h2>
            <p className="mt-0.5 max-w-lg text-xs text-muted-foreground">
              Phase 2 live — strategies routed through the fill simulator and position
              tracker via{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                src/strategies/&lt;name&gt;/
              </code>
            </p>
          </div>
          <RoadmapTimeline />
        </section>
      </div>

      {/* Sidebar */}
      <aside className="space-y-6">
        <SystemHealth />
      </aside>
    </div>
  );
}

/* ── LiveBadge ──────────────────────────────────────────────────────────────── */

function LiveBadge() {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-profit/25 bg-profit/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-widest text-profit">
      <span
        className="h-1.5 w-1.5 rounded-full bg-profit"
        style={{ animation: "pulse-dot 2s ease-in-out infinite" }}
        aria-hidden="true"
      />
      Phase 2 · Live
    </div>
  );
}

/* ── MetricCard ─────────────────────────────────────────────────────────────── */

type Accent = "profit" | "highlight" | "sky" | "amber";

const BORDER: Record<Accent, string> = {
  profit:    "from-profit/25 via-profit/5 to-transparent",
  highlight: "from-highlight/25 via-highlight/5 to-transparent",
  sky:       "from-sky-500/25 via-sky-500/5 to-transparent",
  amber:     "from-amber-400/25 via-amber-400/5 to-transparent",
};
const VALUE_CLS: Record<Accent, string> = {
  profit:    "text-profit",
  highlight: "text-highlight",
  sky:       "text-sky-400",
  amber:     "text-amber-400",
};
const DOT_CLS: Record<Accent, string> = {
  profit:    "bg-profit",
  highlight: "bg-highlight",
  sky:       "bg-sky-400",
  amber:     "bg-amber-400",
};

function MetricCard({
  label, sublabel, value, sub, accent,
}: {
  label: string; sublabel: string; value: string; sub: string; accent: Accent;
}) {
  return (
    <div className={cn("group rounded-xl bg-gradient-to-br p-px transition-all duration-300 hover:shadow-lg", BORDER[accent])}>
      <div className="flex h-full flex-col justify-between gap-4 rounded-xl bg-card p-5">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
              {label}
            </div>
            <div className="mt-0.5 text-[10px] text-muted-foreground/50">{sublabel}</div>
          </div>
          <div className={cn("mt-0.5 h-2 w-2 shrink-0 rounded-full opacity-60", DOT_CLS[accent])} />
        </div>
        <div>
          <div className={cn("font-mono text-4xl font-bold leading-none tracking-tight", VALUE_CLS[accent])}>
            {value}
          </div>
          <div className="mt-2 text-[11px] text-muted-foreground/60">{sub}</div>
        </div>
      </div>
    </div>
  );
}

/* ── Roadmap Timeline ───────────────────────────────────────────────────────── */

const ROADMAP: { status: "done" | "active" | "upcoming"; phase: string; label: string }[] = [
  { status: "done",     phase: "Phase 0",  label: "Scaffolding, interfaces, configs, schema" },
  { status: "done",     phase: "Phase 1",  label: "Ingestion pipes + System Health" },
  { status: "active",   phase: "Phase 2",  label: "Fill simulator + position tracker + sleeve P&L" },
  { status: "upcoming", phase: "Phase 3",  label: "Full dashboard + replay engine + tag system" },
  { status: "upcoming", phase: "Phase 4",  label: "Strategy template + reference strategy" },
  { status: "upcoming", phase: "Phase 5+", label: "Strategies one-by-one with full rigor" },
];

function RoadmapTimeline() {
  return (
    <div className="rounded-xl border border-border/60 bg-card p-6">
      {ROADMAP.map(({ status, phase, label }, i) => (
        <div key={phase} className="flex gap-4">
          {/* Gutter */}
          <div className="flex flex-col items-center">
            <TimelineDot status={status} />
            {i < ROADMAP.length - 1 && (
              <div className={cn("mt-1 w-px flex-1", status === "done" ? "bg-profit/20" : "bg-border/50")} />
            )}
          </div>
          {/* Content */}
          <div className={cn("min-w-0 flex-1 pb-5", i === ROADMAP.length - 1 && "pb-0")}>
            <div className="flex items-center gap-2">
              <span className={cn(
                "text-[10px] font-bold uppercase tracking-widest",
                status === "done"     && "text-profit/50",
                status === "active"   && "text-amber-400",
                status === "upcoming" && "text-muted-foreground/40",
              )}>
                {phase}
              </span>
              {status === "active" && (
                <span className="rounded-full bg-amber-400/15 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-widest text-amber-400">
                  in progress
                </span>
              )}
              {status === "done" && (
                <span className="rounded-full bg-profit/10 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-widest text-profit/60">
                  done
                </span>
              )}
            </div>
            <div className={cn(
              "mt-0.5 text-sm",
              status === "done"     && "line-through text-muted-foreground/35 decoration-muted-foreground/20",
              status === "active"   && "font-semibold text-foreground",
              status === "upcoming" && "text-muted-foreground/50",
            )}>
              {label}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function TimelineDot({ status }: { status: "done" | "active" | "upcoming" }) {
  if (status === "done") {
    return (
      <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-profit/25 bg-profit/15">
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
          <path d="M2 5l2.2 2.2L8 3" stroke="hsl(var(--profit))" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
    );
  }
  if (status === "active") {
    return (
      <div
        className="h-5 w-5 shrink-0 rounded-full border-2 border-amber-400 bg-amber-400/20"
        style={{ animation: "pulse-dot 2s ease-in-out infinite" }}
        aria-label="In progress"
      />
    );
  }
  return (
    <div className="h-5 w-5 shrink-0 rounded-full border border-border/60 bg-muted/20" aria-label="Upcoming" />
  );
}

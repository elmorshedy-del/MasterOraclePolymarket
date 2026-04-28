import { SleevesTable } from "@/components/SleevesTable";
import { SystemHealth } from "@/components/SystemHealth";

export default function OverviewPage() {
  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-[1fr_280px]">
      <div className="space-y-8">
        <section>
          <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Phase 2 — fill simulator and position tracker online. Add a sleeve YAML to start running.
          </p>
        </section>

        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card label="Total P&L (after −22% haircut)" value="—" sub="awaiting first sleeve" />
          <Card label="Active sleeves" value="0" sub="0 in live_full" />
          <Card label="Trades today" value="0" sub="across all modes" />
          <Card label="Ingestion" value="live" sub="see sidebar →" />
        </section>

        <section className="space-y-3">
          <div className="flex items-baseline justify-between">
            <h2 className="text-sm font-medium text-muted-foreground">Sleeves</h2>
            <a
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              href="/sleeves"
            >
              View all →
            </a>
          </div>
          <SleevesTable />
        </section>

        <section className="rounded-lg border border-border/60 bg-card p-6">
          <h2 className="text-sm font-medium text-muted-foreground">Status</h2>
          <p className="mt-2 text-sm">
            Phase 2 is live. Strategies plugged in via{" "}
            <code className="rounded bg-muted px-1.5 py-0.5 text-[12px]">
              src/strategies/&lt;name&gt;/
            </code>{" "}
            and configured via sleeve YAMLs are routed through the fill simulator
            and position tracker. Trades feed the analytics pipeline.
          </p>
          <ul className="mt-4 space-y-2 text-sm text-muted-foreground">
            <li>✓ Phase 0: scaffolding, interfaces, configs, schema</li>
            <li>✓ Phase 1: ingestion pipes + System Health</li>
            <li>● Phase 2: fill simulator + position tracker + sleeve P&L</li>
            <li>→ Phase 3: full dashboard + replay engine + tag system</li>
            <li>→ Phase 4: strategy template + reference strategy</li>
            <li>→ Phase 5+: strategies one-by-one with full rigor</li>
          </ul>
        </section>
      </div>

      <aside className="space-y-6">
        <SystemHealth />
      </aside>
    </div>
  );
}

function Card({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-lg border border-border/60 bg-card p-5">
      <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight">{value}</div>
      <div className="mt-1 text-xs text-muted-foreground">{sub}</div>
    </div>
  );
}

"use client";

import useSWR from "swr";

import { fetcher } from "@/lib/utils";

type Health = {
  checked_at: string;
  db: {
    status: string;
    server_time: string | null;
    events_last_5min: number | null;
  };
  orderbooks: {
    markets_in_memory: number;
    asset_books_in_memory: number;
    snapshots_applied_total: number;
    deltas_applied_total: number;
  };
};

export function SystemHealth() {
  const { data, error, isLoading } = useSWR<Health>(
    "/api/backend/system/health",
    fetcher,
    { refreshInterval: 5_000 },
  );

  const dbOk = data?.db.status === "ok";
  const eventsRate = data?.db.events_last_5min ?? null;
  const eventsHealthy = eventsRate !== null && eventsRate > 0;
  const overallOk = !error && (dbOk ?? false);

  return (
    <div className="relative overflow-hidden rounded-xl border border-border/60 bg-card">
      {/* Ambient glow — shifts color based on health */}
      <div
        className="pointer-events-none absolute -right-10 -top-10 h-28 w-28 rounded-full blur-3xl transition-colors duration-700"
        style={{ backgroundColor: `hsl(var(--${overallOk ? "profit" : "loss"}) / 0.07)` }}
        aria-hidden="true"
      />

      {/* Header */}
      <div className="relative flex items-center justify-between border-b border-border/40 px-5 py-4">
        <h3 className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
          System Health
        </h3>
        <StatusBadge ok={overallOk} loading={isLoading} />
      </div>

      {/* Body */}
      <div className="relative px-5 py-4">
        {isLoading && (
          <p className="text-xs text-muted-foreground">Checking…</p>
        )}
        {error && (
          <p className="text-xs text-loss">Could not reach API.</p>
        )}
        {data && (
          <dl className="space-y-0">
            <HealthGroup>
              <HealthRow label="Database" value={data.db.status} ok={dbOk} />
              <HealthRow
                label="Events / 5 min"
                value={eventsRate !== null ? eventsRate.toLocaleString() : "—"}
                ok={eventsHealthy}
              />
            </HealthGroup>

            <Divider />

            <HealthGroup>
              <HealthRow
                label="Markets"
                value={data.orderbooks.markets_in_memory.toLocaleString()}
                ok={data.orderbooks.markets_in_memory > 0}
              />
              <HealthRow
                label="Asset books"
                value={data.orderbooks.asset_books_in_memory.toLocaleString()}
                ok={data.orderbooks.asset_books_in_memory > 0}
              />
            </HealthGroup>

            <Divider />

            <HealthGroup>
              <HealthRow
                label="Snapshots"
                value={data.orderbooks.snapshots_applied_total.toLocaleString()}
              />
              <HealthRow
                label="Deltas"
                value={data.orderbooks.deltas_applied_total.toLocaleString()}
              />
            </HealthGroup>
          </dl>
        )}
      </div>
    </div>
  );
}

function HealthGroup({ children }: { children: React.ReactNode }) {
  return <div className="space-y-2.5 py-3">{children}</div>;
}

function Divider() {
  return <div className="border-t border-border/40" />;
}

function StatusBadge({ ok, loading }: { ok: boolean; loading: boolean }) {
  if (loading) {
    return <span className="text-[10px] text-muted-foreground">…</span>;
  }
  return (
    <div className="flex items-center gap-1.5">
      <span
        className="h-2 w-2 rounded-full"
        style={{
          backgroundColor: `hsl(var(--${ok ? "profit" : "loss"}))`,
          animation: ok ? "pulse-dot 2s ease-in-out infinite" : "none",
        }}
        aria-hidden="true"
      />
      <span
        className="font-mono text-[10px] font-bold uppercase tracking-widest"
        style={{ color: `hsl(var(--${ok ? "profit" : "loss"}))` }}
      >
        {ok ? "live" : "down"}
      </span>
    </div>
  );
}

function HealthRow({
  label, value, ok,
}: {
  label: string; value: string; ok?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="text-xs text-muted-foreground/70">{label}</dt>
      <dd className="flex shrink-0 items-center gap-1.5 font-mono text-xs">
        <span className={
          ok === true ? "text-foreground" :
          ok === false ? "text-loss" :
          "text-muted-foreground"
        }>
          {value}
        </span>
        {ok !== undefined && (
          <span
            className="h-1.5 w-1.5 rounded-full"
            style={{ backgroundColor: `hsl(var(--${ok ? "profit" : "loss"}))` }}
            aria-hidden="true"
          />
        )}
      </dd>
    </div>
  );
}

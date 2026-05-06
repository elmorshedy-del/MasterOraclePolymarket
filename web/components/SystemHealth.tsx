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

  return (
    <div className="rounded-lg border border-border/60 bg-card p-5">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-muted-foreground">System Health</h3>
        <Dot ok={!error && (dbOk ?? false)} />
      </div>

      {isLoading && (
        <div className="mt-3 text-xs text-muted-foreground">Checking…</div>
      )}

      {error && (
        <div className="mt-3 text-xs text-loss">Could not reach API.</div>
      )}

      {data && (
        <dl className="mt-4 space-y-2 text-xs">
          <Row label="Database" value={data.db.status} ok={dbOk} />
          <Row
            label="Events (last 5m)"
            value={eventsRate !== null ? eventsRate.toLocaleString() : "—"}
            ok={eventsHealthy}
          />
          <Row
            label="Markets in memory"
            value={data.orderbooks.markets_in_memory.toLocaleString()}
            ok={data.orderbooks.markets_in_memory > 0}
          />
          <Row
            label="Asset books"
            value={data.orderbooks.asset_books_in_memory.toLocaleString()}
            ok={data.orderbooks.asset_books_in_memory > 0}
          />
          <Row
            label="Book snapshots"
            value={data.orderbooks.snapshots_applied_total.toLocaleString()}
          />
          <Row
            label="Book deltas"
            value={data.orderbooks.deltas_applied_total.toLocaleString()}
          />
        </dl>
      )}
    </div>
  );
}

function Row({
  label,
  value,
  ok,
}: {
  label: string;
  value: string;
  ok?: boolean;
}) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="flex items-center gap-2 font-mono">
        <span>{value}</span>
        {ok !== undefined && <Dot ok={ok} small />}
      </dd>
    </div>
  );
}

function Dot({ ok, small }: { ok: boolean; small?: boolean }) {
  const size = small ? "h-1.5 w-1.5" : "h-2 w-2";
  const color = ok ? "bg-profit" : "bg-loss";
  return <span className={`inline-block rounded-full ${size} ${color}`} />;
}

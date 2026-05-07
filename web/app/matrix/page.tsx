"use client";

import { useState } from "react";
import useSWR from "swr";

import { cn, fetcher, formatUsd } from "@/lib/utils";

const DIMS = [
  "strategy_name",
  "config_id",
  "market_category",
  "market_subcategory",
  "liquidity_bucket",
  "entry_price_bucket",
  "time_to_resolution_bucket",
  "orderbook_state_bucket",
  "time_of_day_bucket",
  "day_of_week",
  "news_regime",
  "counterparty_estimate",
  "fill_type",
  "realism_flag",
  "source",
  "slippage_bucket",
];

const METRICS = ["total_pnl", "trade_count", "win_rate", "avg_pnl"];

type Cell = {
  row_key: string | null;
  col_key: string | null;
  total_pnl: number;
  trade_count: number;
  win_rate: number | null;
  avg_pnl: number | null;
};

export default function MatrixPage() {
  const [row, setRow] = useState("strategy_name");
  const [col, setCol] = useState("market_category");
  const [metric, setMetric] = useState<"total_pnl" | "trade_count" | "win_rate" | "avg_pnl">("total_pnl");
  const [hours, setHours] = useState(168);

  const { data } = useSWR<{ cells: Cell[] }>(
    `/api/backend/analytics/pivot?row=${row}&col=${col}&metric=${metric}&hours=${hours}`,
    fetcher,
  );

  const cells = data?.cells ?? [];
  const rowKeys = Array.from(new Set(cells.map((c) => c.row_key ?? "—")));
  const colKeys = Array.from(new Set(cells.map((c) => c.col_key ?? "—")));
  const grid: Record<string, Record<string, Cell>> = {};
  for (const cell of cells) {
    const r = cell.row_key ?? "—";
    const c = cell.col_key ?? "—";
    grid[r] = grid[r] ?? {};
    grid[r][c] = cell;
  }

  const values = cells.map((c) => valueFor(c, metric)).filter((v): v is number => Number.isFinite(v));
  const minV = values.length > 0 ? Math.min(...values) : 0;
  const maxV = values.length > 0 ? Math.max(...values) : 0;

  return (
    <div className="space-y-8">

      {/* Hero */}
      <section>
        <h1 className="text-[2rem] font-bold tracking-tight">Matrix</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Pivot any two tags. Cell color intensity = {metric.replace(/_/g, " ")}. Values reflect after-haircut.
        </p>
      </section>

      {/* Controls */}
      <section className="flex flex-wrap items-end gap-3">
        <Picker label="Rows" value={row} onChange={setRow} options={DIMS} />
        <Picker label="Cols" value={col} onChange={setCol} options={DIMS} />
        <Picker label="Metric" value={metric} onChange={(v) => setMetric(v as typeof metric)} options={METRICS} />
        <Picker
          label="Window"
          value={String(hours)}
          onChange={(v) => setHours(Number(v))}
          options={["24", "72", "168", "720", "2160"]}
          formatLabel={(v) => `${v}h`}
        />
      </section>

      {/* Matrix table */}
      {cells.length === 0 ? (
        <div className="flex flex-col items-center rounded-xl border border-dashed border-border/50 bg-card/40 px-6 py-14 text-center">
          <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full border border-border/60 bg-muted">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" className="text-muted-foreground" aria-hidden="true">
              <rect x="1" y="1" width="6" height="6" rx="1" />
              <rect x="9" y="1" width="6" height="6" rx="1" />
              <rect x="1" y="9" width="6" height="6" rx="1" />
              <rect x="9" y="9" width="6" height="6" rx="1" />
            </svg>
          </div>
          <p className="text-sm font-medium text-muted-foreground">No data for this pivot</p>
          <p className="mt-1 text-xs text-muted-foreground/60">Try adjusting the time window or dimensions</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border/60">
          <table className="text-xs">
            <thead className="border-b border-border/60 bg-muted/30">
              <tr>
                <th className="sticky left-0 z-10 bg-muted/30 px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-muted-foreground/70 backdrop-blur">
                  {row} \ {col}
                </th>
                {colKeys.map((c) => (
                  <th key={c} className="px-3 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-muted-foreground/70">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rowKeys.map((r) => (
                <tr key={r} className="border-t border-border/40">
                  <th className="sticky left-0 z-10 bg-card px-4 py-2.5 text-left font-mono text-[11px] font-semibold text-foreground">
                    {r}
                  </th>
                  {colKeys.map((c) => {
                    const cell = grid[r]?.[c];
                    if (!cell) return <td key={c} className="px-3 py-2.5" />;
                    const v = valueFor(cell, metric);
                    return (
                      <td
                        key={c}
                        className="px-3 py-2.5 text-right transition-colors"
                        style={{ backgroundColor: cellColor(v, minV, maxV, metric) }}
                        title={`${cell.trade_count} trades · pnl ${formatUsd(cell.total_pnl)}`}
                      >
                        <span className="font-mono font-semibold">{displayCell(cell, metric)}</span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Picker({
  label, value, onChange, options, formatLabel,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
  formatLabel?: (v: string) => string;
}) {
  return (
    <label className="space-y-1.5">
      <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/70">{label}</div>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="cursor-pointer rounded-xl border border-border bg-card px-3 py-2 font-mono text-[12px] text-foreground transition-colors focus:outline-none focus:ring-2 focus:ring-ring"
      >
        {options.map((o) => (
          <option key={o} value={o}>{formatLabel ? formatLabel(o) : o}</option>
        ))}
      </select>
    </label>
  );
}

function valueFor(c: Cell, metric: string): number {
  switch (metric) {
    case "trade_count": return c.trade_count;
    case "win_rate": return c.win_rate ?? 0;
    case "avg_pnl": return c.avg_pnl ?? 0;
    default: return c.total_pnl;
  }
}

function displayCell(c: Cell, metric: string): string {
  switch (metric) {
    case "trade_count": return String(c.trade_count);
    case "win_rate": return `${((c.win_rate ?? 0) * 100).toFixed(0)}%`;
    case "avg_pnl": return formatUsd(c.avg_pnl ?? 0);
    default: return formatUsd(c.total_pnl);
  }
}

function cellColor(v: number, minV: number, maxV: number, metric: string): string {
  if (!Number.isFinite(v)) return "transparent";
  if (metric === "trade_count") {
    const denom = maxV || 1;
    const t = Math.max(0, Math.min(1, v / denom));
    return `hsl(220 30% ${100 - t * 80}% / 0.10)`;
  }
  if (v >= 0) {
    const denom = maxV || 1;
    const t = Math.max(0, Math.min(1, v / denom));
    return `hsl(var(--profit) / ${0.1 + t * 0.4})`;
  }
  const denom = -minV || 1;
  const t = Math.max(0, Math.min(1, -v / denom));
  return `hsl(var(--loss) / ${0.1 + t * 0.4})`;
}

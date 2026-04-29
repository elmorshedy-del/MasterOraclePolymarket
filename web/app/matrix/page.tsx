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

  // Color scaling for the chosen metric
  const values = cells.map((c) => valueFor(c, metric)).filter((v): v is number => Number.isFinite(v));
  const minV = values.length > 0 ? Math.min(...values) : 0;
  const maxV = values.length > 0 ? Math.max(...values) : 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Matrix</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Pivot any two tags. Cell color = {metric.replace("_", " ")}. Numbers reflect after-haircut values.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Picker label="Rows" value={row} onChange={setRow} options={DIMS} />
        <Picker label="Cols" value={col} onChange={setCol} options={DIMS} />
        <Picker label="Metric" value={metric} onChange={(v) => setMetric(v as any)} options={METRICS} />
        <Picker
          label="Window"
          value={String(hours)}
          onChange={(v) => setHours(Number(v))}
          options={["24", "72", "168", "720", "2160"]}
        />
      </div>

      <div className="overflow-x-auto rounded-lg border border-border/60">
        <table className="text-xs">
          <thead className="bg-muted/40">
            <tr>
              <th className="sticky left-0 z-10 bg-muted/40 px-3 py-2 text-left text-muted-foreground">
                {row} \ {col}
              </th>
              {colKeys.map((c) => (
                <th key={c} className="px-3 py-2 text-left font-mono text-[11px] text-muted-foreground">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rowKeys.map((r) => (
              <tr key={r} className="border-t border-border/40">
                <th className="sticky left-0 bg-card px-3 py-2 text-left font-mono text-[11px] text-foreground">
                  {r}
                </th>
                {colKeys.map((c) => {
                  const cell = grid[r]?.[c];
                  if (!cell) return <td key={c} className="px-3 py-2" />;
                  const v = valueFor(cell, metric);
                  return (
                    <td
                      key={c}
                      className="px-3 py-2 text-right"
                      style={{ background: cellColor(v, minV, maxV, metric) }}
                      title={`${cell.trade_count} trades · pnl ${formatUsd(cell.total_pnl)}`}
                    >
                      <span className="font-mono">{displayCell(cell, metric)}</span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Picker({
  label, value, onChange, options,
}: { label: string; value: string; onChange: (v: string) => void; options: string[] }) {
  return (
    <label className="flex items-center gap-2 text-xs text-muted-foreground">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-border bg-card px-2 py-1 font-mono text-[12px] text-foreground"
      >
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
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

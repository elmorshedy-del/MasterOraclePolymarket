"use client";

import { use } from "react";

import { PromotionPanel } from "@/components/PromotionPanel";
import { useApi } from "@/lib/api";
import { cn, formatUsd } from "@/lib/utils";

type Metrics = { sleeve_id: string; trade_count: number; metrics: Record<string, number> };
type Trade = {
  trade_id: string;
  market_id: string;
  side: string;
  entry_price: number;
  exit_price: number | null;
  pnl_after_haircut_usd: number | null;
  fill_type: string;
  realism_flag: string;
  market_category: string | null;
};
type PnlPoint = {
  ts: string;
  realized_pnl_usd: number;
  unrealized_pnl_usd: number;
  capital_remaining: number;
};

export default function SleeveDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: m } = useApi<Metrics>(`/analytics/sleeve_metrics?sleeve_id=${encodeURIComponent(id)}`, 15_000);
  const { data: t } = useApi<{ trades: Trade[] }>(
    `/system/recent_trades?sleeve_id=${encodeURIComponent(id)}&limit=100`,
    10_000,
  );
  const { data: p } = useApi<{ points: PnlPoint[] }>(
    `/system/sleeve_pnl?sleeve_id=${encodeURIComponent(id)}&hours=720`,
    30_000,
  );

  const metrics = m?.metrics ?? {};
  const trades = t?.trades ?? [];
  const points = p?.points ?? [];

  return (
    <div className="space-y-8">
      <section>
        <div className="text-xs uppercase tracking-wider text-muted-foreground">Sleeve</div>
        <h1 className="mt-1 font-mono text-xl font-semibold tracking-tight">{id}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {m?.trade_count ?? 0} trades recorded.
        </p>
      </section>

      <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          ["Total P&L (haircut)", formatUsd(metrics.total_pnl ?? 0, { sign: true }), (metrics.total_pnl ?? 0) >= 0 ? "text-profit" : "text-loss"],
          ["Sharpe", (metrics.sharpe ?? 0).toFixed(2), null],
          ["Sortino", (metrics.sortino ?? 0).toFixed(2), null],
          ["Max DD", formatUsd(metrics.max_drawdown ?? 0), "text-loss"],
          ["Win rate", `${((metrics.win_rate ?? 0) * 100).toFixed(1)}%`, null],
          ["Profit factor", (metrics.profit_factor ?? 0).toFixed(2), null],
          ["Avg trade", formatUsd(metrics.avg_trade ?? 0, { sign: true }), null],
          // Walk-derived measured friction; replaces the literature haircut
          // as the headline gap-to-real-money signal.
          ["Avg slippage", `${(metrics.avg_slippage_bps ?? 0).toFixed(1)} bps`, null],
          ["Capacity", `${((metrics.capacity_estimate ?? 0) * 100).toFixed(2)}%`, null],
        ].map(([label, value, color]) => (
          <div key={label as string} className="rounded-lg border border-border/60 bg-card p-4">
            <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              {label}
            </div>
            <div className={cn("mt-2 font-mono text-lg font-semibold", color as string)}>
              {value}
            </div>
          </div>
        ))}
      </section>

      <section>
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">Equity curve (30d)</h2>
        <EquityChart points={points} />
      </section>

      <section>
        <PromotionPanel sleeveId={id} />
      </section>

      <section>
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">Recent trades</h2>
        <TradesTable trades={trades} />
      </section>
    </div>
  );
}

function EquityChart({ points }: { points: PnlPoint[] }) {
  if (points.length < 2) {
    return (
      <div className="rounded-lg border border-dashed border-border/60 p-8 text-center text-sm text-muted-foreground">
        Not enough data yet.
      </div>
    );
  }

  // Simple inline SVG sparkline — no extra dep, looks good.
  const W = 800;
  const H = 200;
  const PAD = 12;
  const xs = points.map((p) => new Date(p.ts).getTime());
  const ys = points.map((p) => Number(p.capital_remaining));
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const dx = maxX - minX || 1;
  const dy = maxY - minY || 1;
  const path = points
    .map((p, i) => {
      const x = PAD + ((xs[i] - minX) / dx) * (W - 2 * PAD);
      const y = H - PAD - ((ys[i] - minY) / dy) * (H - 2 * PAD);
      return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
  const last = ys[ys.length - 1];
  const first = ys[0];
  const positive = last >= first;
  return (
    <div className="rounded-lg border border-border/60 bg-card p-4">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-48 w-full">
        <path
          d={path}
          stroke={positive ? "hsl(var(--profit))" : "hsl(var(--loss))"}
          strokeWidth={2}
          fill="none"
        />
      </svg>
      <div className="mt-2 flex justify-between text-xs text-muted-foreground">
        <span>start: {formatUsd(first, { cents: false })}</span>
        <span>now: {formatUsd(last, { cents: false })}</span>
      </div>
    </div>
  );
}

function TradesTable({ trades }: { trades: Trade[] }) {
  if (trades.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border/60 p-8 text-center text-sm text-muted-foreground">
        No trades yet.
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-lg border border-border/60">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left">Market</th>
            <th className="px-3 py-2 text-left">Side</th>
            <th className="px-3 py-2 text-right">Entry</th>
            <th className="px-3 py-2 text-right">Exit</th>
            <th className="px-3 py-2 text-right">P&L</th>
            <th className="px-3 py-2 text-left">Fill</th>
            <th className="px-3 py-2 text-left">Flag</th>
            <th className="px-3 py-2 text-left">Cat</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((tr) => {
            const pnl = Number(tr.pnl_after_haircut_usd ?? 0);
            const cls = pnl > 0 ? "text-profit" : pnl < 0 ? "text-loss" : "";
            return (
              <tr key={tr.trade_id} className="border-t border-border/40 hover:bg-muted/20">
                <td className="px-3 py-2 font-mono text-[12px]">
                  {tr.market_id.slice(0, 14)}…
                </td>
                <td className="px-3 py-2">{tr.side}</td>
                <td className="px-3 py-2 text-right font-mono">{tr.entry_price.toFixed(3)}</td>
                <td className="px-3 py-2 text-right font-mono">
                  {tr.exit_price === null ? "—" : tr.exit_price.toFixed(3)}
                </td>
                <td className={cn("px-3 py-2 text-right font-mono", cls)}>
                  {formatUsd(pnl, { sign: true })}
                </td>
                <td className="px-3 py-2 text-xs text-muted-foreground">{tr.fill_type}</td>
                <td className="px-3 py-2 text-xs text-muted-foreground">{tr.realism_flag}</td>
                <td className="px-3 py-2 text-xs text-muted-foreground">
                  {tr.market_category ?? "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

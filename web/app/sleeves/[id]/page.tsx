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

type Accent = "profit" | "loss" | "highlight" | "sky" | "amber" | "neutral";

const METRIC_CONFIG: {
  key: string;
  label: string;
  accent: Accent;
  format: (v: number) => string;
}[] = [
  { key: "total_pnl",        label: "Total P&L (haircut)",  accent: "profit",    format: (v) => formatUsd(v, { sign: true }) },
  { key: "sharpe",           label: "Sharpe",               accent: "highlight", format: (v) => v.toFixed(2) },
  { key: "sortino",          label: "Sortino",              accent: "sky",       format: (v) => v.toFixed(2) },
  { key: "max_drawdown",     label: "Max Drawdown",         accent: "loss",      format: (v) => formatUsd(v) },
  { key: "win_rate",         label: "Win Rate",             accent: "profit",    format: (v) => `${(v * 100).toFixed(1)}%` },
  { key: "profit_factor",    label: "Profit Factor",        accent: "highlight", format: (v) => v.toFixed(2) },
  { key: "avg_trade",        label: "Avg Trade",            accent: "sky",       format: (v) => formatUsd(v, { sign: true }) },
  { key: "avg_slippage_bps", label: "Avg Slippage",         accent: "amber",     format: (v) => `${v.toFixed(1)} bps` },
  { key: "capacity_estimate",label: "Capacity",             accent: "neutral",   format: (v) => `${(v * 100).toFixed(2)}%` },
];

const BORDER_CLS: Record<Accent, string> = {
  profit:    "from-profit/25 via-profit/5 to-transparent",
  loss:      "from-loss/20 via-loss/5 to-transparent",
  highlight: "from-highlight/25 via-highlight/5 to-transparent",
  sky:       "from-sky-500/25 via-sky-500/5 to-transparent",
  amber:     "from-amber-400/25 via-amber-400/5 to-transparent",
  neutral:   "from-border/60 via-border/20 to-transparent",
};

const VALUE_CLS: Record<Accent, string> = {
  profit:    "text-profit",
  loss:      "text-loss",
  highlight: "text-highlight",
  sky:       "text-sky-400",
  amber:     "text-amber-400",
  neutral:   "text-foreground",
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
    <div className="space-y-10">

      {/* Hero */}
      <section className="space-y-1">
        <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/60">Sleeve</div>
        <h1 className="font-mono text-[2rem] font-bold tracking-tight">{id}</h1>
        <p className="text-sm text-muted-foreground">
          {m?.trade_count ?? 0} trades recorded.
        </p>
      </section>

      {/* Metrics grid */}
      <section className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
        {METRIC_CONFIG.map(({ key, label, accent, format }) => {
          const raw = metrics[key] ?? 0;
          return (
            <div
              key={key}
              className={cn("rounded-xl bg-gradient-to-br p-px", BORDER_CLS[accent])}
            >
              <div className="flex flex-col gap-2 rounded-xl bg-card p-4">
                <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/70">
                  {label}
                </div>
                <div className={cn("font-mono text-xl font-bold leading-none tracking-tight", VALUE_CLS[accent])}>
                  {format(raw)}
                </div>
              </div>
            </div>
          );
        })}
      </section>

      {/* Equity chart */}
      <section className="space-y-3">
        <div>
          <h2 className="text-sm font-semibold tracking-tight">Equity Curve</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">30-day capital remaining</p>
        </div>
        <EquityChart points={points} />
      </section>

      {/* Promotion */}
      <section>
        <PromotionPanel sleeveId={id} />
      </section>

      {/* Recent trades */}
      <section className="space-y-3">
        <div>
          <h2 className="text-sm font-semibold tracking-tight">Recent Trades</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">Latest 100 closed trades</p>
        </div>
        <TradesTable trades={trades} />
      </section>
    </div>
  );
}

function EquityChart({ points }: { points: PnlPoint[] }) {
  if (points.length < 2) {
    return (
      <div className="flex flex-col items-center rounded-xl border border-dashed border-border/50 bg-card/40 px-6 py-12 text-center">
        <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full border border-border/60 bg-muted">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" className="text-muted-foreground" aria-hidden="true">
            <polyline points="1,12 5,7 9,9 15,3" />
          </svg>
        </div>
        <p className="text-sm font-medium text-muted-foreground">Not enough data yet</p>
        <p className="mt-1 text-xs text-muted-foreground/60">Equity curve appears after 2+ data points</p>
      </div>
    );
  }

  const W = 800;
  const H = 200;
  const PAD = 16;
  const xs = points.map((pt) => new Date(pt.ts).getTime());
  const ys = points.map((pt) => Number(pt.capital_remaining));
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const dx = maxX - minX || 1;
  const dy = maxY - minY || 1;

  const pts = points.map((pt, i) => ({
    x: PAD + ((xs[i] - minX) / dx) * (W - 2 * PAD),
    y: H - PAD - ((ys[i] - minY) / dy) * (H - 2 * PAD),
  }));

  const linePath = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");

  // Area fill path
  const areaPath =
    `M ${pts[0].x.toFixed(1)} ${H} ` +
    pts.map((p) => `L ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ") +
    ` L ${pts[pts.length - 1].x.toFixed(1)} ${H} Z`;

  const last = ys[ys.length - 1];
  const first = ys[0];
  const positive = last >= first;
  const colorVar = positive ? "--profit" : "--loss";

  return (
    <div className="overflow-hidden rounded-xl border border-border/60 bg-card">
      <div className="px-5 pt-5 pb-3">
        <svg viewBox={`0 0 ${W} ${H}`} className="h-44 w-full">
          <defs>
            <linearGradient id="equity-area-grad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={`hsl(var(${colorVar}))`} stopOpacity="0.15" />
              <stop offset="100%" stopColor={`hsl(var(${colorVar}))`} stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={areaPath} fill="url(#equity-area-grad)" />
          <path
            d={linePath}
            stroke={`hsl(var(${colorVar}))`}
            strokeWidth={2}
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {/* End-point dot */}
          <circle
            cx={pts[pts.length - 1].x}
            cy={pts[pts.length - 1].y}
            r={4}
            fill={`hsl(var(${colorVar}))`}
          />
        </svg>
      </div>
      <div className="flex justify-between border-t border-border/40 px-5 py-3">
        <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/60">
          Start <span className="ml-1 font-mono text-xs font-semibold text-foreground">{formatUsd(first, { cents: false })}</span>
        </div>
        <div className={cn("text-[10px] font-bold uppercase tracking-widest", positive ? "text-profit/70" : "text-loss/70")}>
          Now <span className={cn("ml-1 font-mono text-xs font-bold", positive ? "text-profit" : "text-loss")}>{formatUsd(last, { cents: false })}</span>
        </div>
      </div>
    </div>
  );
}

function TradesTable({ trades }: { trades: Trade[] }) {
  if (trades.length === 0) {
    return (
      <div className="flex flex-col items-center rounded-xl border border-dashed border-border/50 bg-card/40 px-6 py-12 text-center">
        <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full border border-border/60 bg-muted">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" className="text-muted-foreground" aria-hidden="true">
            <rect x="1" y="5" width="14" height="10" rx="1.25" />
            <path d="M5 5V3.5a3 3 0 0 1 6 0V5" />
          </svg>
        </div>
        <p className="text-sm font-medium text-muted-foreground">No trades yet</p>
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-xl border border-border/60">
      <table className="w-full text-sm">
        <thead className="border-b border-border/60 bg-muted/30 text-[10px] font-bold uppercase tracking-widest text-muted-foreground/70">
          <tr>
            <th className="px-4 py-3 text-left">Market</th>
            <th className="px-4 py-3 text-left">Side</th>
            <th className="px-4 py-3 text-right">Entry</th>
            <th className="px-4 py-3 text-right">Exit</th>
            <th className="px-4 py-3 text-right">P&L</th>
            <th className="px-4 py-3 text-left">Fill</th>
            <th className="px-4 py-3 text-left">Flag</th>
            <th className="px-4 py-3 text-left">Cat</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((tr) => {
            const pnl = Number(tr.pnl_after_haircut_usd ?? 0);
            const cls = pnl > 0 ? "text-profit" : pnl < 0 ? "text-loss" : "";
            return (
              <tr key={tr.trade_id} className="border-t border-border/40 hover:bg-muted/20">
                <td className="px-4 py-2.5 font-mono text-[12px]">
                  {tr.market_id.length > 16 ? `${tr.market_id.slice(0, 16)}…` : tr.market_id}
                </td>
                <td className="px-4 py-2.5 text-sm">{tr.side}</td>
                <td className="px-4 py-2.5 text-right font-mono">{tr.entry_price.toFixed(3)}</td>
                <td className="px-4 py-2.5 text-right font-mono">
                  {tr.exit_price === null ? "—" : tr.exit_price.toFixed(3)}
                </td>
                <td className={cn("px-4 py-2.5 text-right font-mono", cls)}>
                  {formatUsd(pnl, { sign: true })}
                </td>
                <td className="px-4 py-2.5 text-xs text-muted-foreground">{tr.fill_type}</td>
                <td className="px-4 py-2.5 text-xs text-muted-foreground">{tr.realism_flag}</td>
                <td className="px-4 py-2.5 text-xs text-muted-foreground">{tr.market_category ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

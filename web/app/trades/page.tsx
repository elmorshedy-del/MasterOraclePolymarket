"use client";

import { useMemo, useState } from "react";

import { useApi } from "@/lib/api";
import { cn, formatUsd } from "@/lib/utils";

type View = "fills" | "positions" | "closed";

type Fill = {
  fill_id: string;
  sleeve_id: string;
  market_id: string;
  asset_id: string;
  side: string;
  price: number | string;
  size: number | string;
  fill_type: string;
  ts_filled: string;
  realism_flag: string;
};

type Position = {
  sleeve_id: string;
  market_id: string;
  asset_id: string;
  side: string;
  size: number | string;
  avg_entry: number | string;
  opened_at: string;
  last_updated: string;
};

type Trade = {
  trade_id: string;
  sleeve_id: string;
  strategy_name: string;
  config_id: string;
  market_id: string;
  side: string;
  entry_price: number | string;
  exit_price: number | string | null;
  entry_size: number | string;
  pnl_after_haircut_usd: number | string | null;
  fill_type: string;
  realism_flag: string;
  market_category: string | null;
  source: string;
};

type Health = {
  db: {
    fills_last_1h?: number;
    trades_last_1h?: number;
    open_positions?: number;
  };
};

export default function TradeExplorerPage() {
  const [view, setView] = useState<View>("fills");
  const [source, setSource] = useState<string>("");
  const [sleeve, setSleeve] = useState<string>("");

  const tradeParams = new URLSearchParams({ limit: "200" });
  if (source) tradeParams.set("source", source);
  if (sleeve) tradeParams.set("sleeve_id", sleeve);

  const positionParams = new URLSearchParams();
  if (sleeve) positionParams.set("sleeve_id", sleeve);
  const positionPath = `/system/positions${positionParams.size ? `?${positionParams}` : ""}`;

  const { data: health } = useApi<Health>("/system/health", 10_000);
  const { data: fillsResp } = useApi<{ fills: Fill[] }>("/system/recent_fills?limit=200", 10_000);
  const { data: positionsResp } = useApi<{ positions: Position[] }>(positionPath, 10_000);
  const { data: tradesResp } = useApi<{ trades: Trade[] }>(`/system/recent_trades?${tradeParams}`, 15_000);

  const fills = useMemo(() => {
    const rows = fillsResp?.fills ?? [];
    return sleeve ? rows.filter((f) => f.sleeve_id === sleeve) : rows;
  }, [fillsResp?.fills, sleeve]);
  const positions = positionsResp?.positions ?? [];
  const trades = tradesResp?.trades ?? [];

  return (
    <div className="space-y-6">
      <section>
        <h1 className="text-2xl font-semibold tracking-tight">Trade Explorer</h1>
      </section>

      <section className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label="Fills last hour" value={String(health?.db.fills_last_1h ?? fills.length)} />
        <StatCard label="Open positions" value={String(health?.db.open_positions ?? positions.length)} />
        <StatCard label="Closed trades last hour" value={String(health?.db.trades_last_1h ?? 0)} />
      </section>

      <section className="flex flex-wrap items-end gap-3">
        <div className="flex rounded-md border border-border/60 bg-card p-1">
          <TabButton active={view === "fills"} onClick={() => setView("fills")}>
            Fills
          </TabButton>
          <TabButton active={view === "positions"} onClick={() => setView("positions")}>
            Open positions
          </TabButton>
          <TabButton active={view === "closed"} onClick={() => setView("closed")}>
            Closed trades
          </TabButton>
        </div>
        <Filter label="Sleeve">
          <input
            type="text"
            value={sleeve}
            onChange={(e) => setSleeve(e.target.value)}
            placeholder="(any)"
            className="w-64 rounded-md border border-border bg-card px-3 py-2 font-mono text-sm"
          />
        </Filter>
        {view === "closed" && (
          <Filter label="Source">
            <select
              value={source}
              onChange={(e) => setSource(e.target.value)}
              className="rounded-md border border-border bg-card px-3 py-2 text-sm"
            >
              <option value="">all</option>
              <option value="live">live</option>
              <option value="replay">replay</option>
            </select>
          </Filter>
        )}
      </section>

      {view === "fills" && <FillsTable fills={fills} />}
      {view === "positions" && <PositionsTable positions={positions} />}
      {view === "closed" && <ClosedTradesTable trades={trades} />}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border/60 bg-card p-4">
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-2 font-mono text-2xl font-semibold tracking-tight">{value}</div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded px-3 py-1.5 text-xs font-medium transition-colors",
        active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function FillsTable({ fills }: { fills: Fill[] }) {
  return (
    <DataTable
      empty="No fills yet."
      colSpan={9}
      header={
        <tr>
          <th className="px-3 py-2 text-left">Time</th>
          <th className="px-3 py-2 text-left">Sleeve</th>
          <th className="px-3 py-2 text-left">Market</th>
          <th className="px-3 py-2 text-left">Asset</th>
          <th className="px-3 py-2 text-left">Side</th>
          <th className="px-3 py-2 text-right">Size</th>
          <th className="px-3 py-2 text-right">Price</th>
          <th className="px-3 py-2 text-left">Fill</th>
          <th className="px-3 py-2 text-left">Flag</th>
        </tr>
      }
    >
      {fills.map((fill) => (
        <tr key={fill.fill_id} className="border-t border-border/40 hover:bg-muted/20">
          <td className="px-3 py-2 text-xs text-muted-foreground">{formatTime(fill.ts_filled)}</td>
          <td className="px-3 py-2 font-mono text-[12px]">{fill.sleeve_id}</td>
          <td className="px-3 py-2 font-mono text-[12px]">{shortId(fill.market_id)}</td>
          <td className="px-3 py-2 font-mono text-[12px]">{shortId(fill.asset_id)}</td>
          <td className="px-3 py-2">{fill.side}</td>
          <td className="px-3 py-2 text-right font-mono">{formatNum(fill.size, 2)}</td>
          <td className="px-3 py-2 text-right font-mono">{formatNum(fill.price, 3)}</td>
          <td className="px-3 py-2 text-xs text-muted-foreground">{fill.fill_type}</td>
          <td className="px-3 py-2 text-xs text-muted-foreground">{fill.realism_flag}</td>
        </tr>
      ))}
    </DataTable>
  );
}

function PositionsTable({ positions }: { positions: Position[] }) {
  return (
    <DataTable
      empty="No open positions."
      colSpan={8}
      header={
        <tr>
          <th className="px-3 py-2 text-left">Opened</th>
          <th className="px-3 py-2 text-left">Sleeve</th>
          <th className="px-3 py-2 text-left">Market</th>
          <th className="px-3 py-2 text-left">Asset</th>
          <th className="px-3 py-2 text-left">Side</th>
          <th className="px-3 py-2 text-right">Size</th>
          <th className="px-3 py-2 text-right">Avg entry</th>
          <th className="px-3 py-2 text-left">Updated</th>
        </tr>
      }
    >
      {positions.map((pos) => (
        <tr
          key={`${pos.sleeve_id}:${pos.market_id}:${pos.asset_id}:${pos.side}`}
          className="border-t border-border/40 hover:bg-muted/20"
        >
          <td className="px-3 py-2 text-xs text-muted-foreground">{formatTime(pos.opened_at)}</td>
          <td className="px-3 py-2 font-mono text-[12px]">{pos.sleeve_id}</td>
          <td className="px-3 py-2 font-mono text-[12px]">{shortId(pos.market_id)}</td>
          <td className="px-3 py-2 font-mono text-[12px]">{shortId(pos.asset_id)}</td>
          <td className="px-3 py-2">{pos.side}</td>
          <td className="px-3 py-2 text-right font-mono">{formatNum(pos.size, 2)}</td>
          <td className="px-3 py-2 text-right font-mono">{formatNum(pos.avg_entry, 3)}</td>
          <td className="px-3 py-2 text-xs text-muted-foreground">{formatTime(pos.last_updated)}</td>
        </tr>
      ))}
    </DataTable>
  );
}

function ClosedTradesTable({ trades }: { trades: Trade[] }) {
  return (
    <DataTable
      empty="No closed trades yet."
      colSpan={12}
      header={
        <tr>
          <th className="px-3 py-2 text-left">Sleeve</th>
          <th className="px-3 py-2 text-left">Strategy/Config</th>
          <th className="px-3 py-2 text-left">Market</th>
          <th className="px-3 py-2 text-left">Cat</th>
          <th className="px-3 py-2 text-left">Side</th>
          <th className="px-3 py-2 text-right">Size</th>
          <th className="px-3 py-2 text-right">Entry</th>
          <th className="px-3 py-2 text-right">Exit</th>
          <th className="px-3 py-2 text-right">P&L</th>
          <th className="px-3 py-2 text-left">Fill</th>
          <th className="px-3 py-2 text-left">Flag</th>
          <th className="px-3 py-2 text-left">Source</th>
        </tr>
      }
    >
      {trades.map((tr) => {
        const pnl = Number(tr.pnl_after_haircut_usd ?? 0);
        const cls = pnl > 0 ? "text-profit" : pnl < 0 ? "text-loss" : "";
        return (
          <tr key={tr.trade_id} className="border-t border-border/40 hover:bg-muted/20">
            <td className="px-3 py-2 font-mono text-[12px]">{tr.sleeve_id}</td>
            <td className="px-3 py-2 text-xs">
              <div>{tr.strategy_name}</div>
              <div className="text-muted-foreground">{tr.config_id}</div>
            </td>
            <td className="px-3 py-2 font-mono text-[12px]">{shortId(tr.market_id)}</td>
            <td className="px-3 py-2 text-xs text-muted-foreground">{tr.market_category ?? "-"}</td>
            <td className="px-3 py-2">{tr.side}</td>
            <td className="px-3 py-2 text-right font-mono">{formatNum(tr.entry_size, 2)}</td>
            <td className="px-3 py-2 text-right font-mono">{formatNum(tr.entry_price, 3)}</td>
            <td className="px-3 py-2 text-right font-mono">
              {tr.exit_price === null ? "-" : formatNum(tr.exit_price, 3)}
            </td>
            <td className={cn("px-3 py-2 text-right font-mono", cls)}>
              {formatUsd(pnl, { sign: true })}
            </td>
            <td className="px-3 py-2 text-xs text-muted-foreground">{tr.fill_type}</td>
            <td className="px-3 py-2 text-xs text-muted-foreground">{tr.realism_flag}</td>
            <td className="px-3 py-2 text-xs text-muted-foreground">{tr.source}</td>
          </tr>
        );
      })}
    </DataTable>
  );
}

function DataTable({
  header,
  children,
  empty,
  colSpan,
}: {
  header: React.ReactNode;
  children: React.ReactNode;
  empty: string;
  colSpan: number;
}) {
  const rows = Array.isArray(children) ? children.length : children ? 1 : 0;
  return (
    <section className="overflow-auto rounded-lg border border-border/60">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
          {header}
        </thead>
        <tbody>
          {children}
          {rows === 0 && (
            <tr>
              <td colSpan={colSpan} className="p-8 text-center text-sm text-muted-foreground">
                {empty}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}

function Filter({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="space-y-1">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
      {children}
    </label>
  );
}

function formatNum(value: number | string | null | undefined, digits: number) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : "-";
}

function formatTime(value: string) {
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function shortId(value: string) {
  if (!value) return "-";
  return value.length > 18 ? `${value.slice(0, 18)}...` : value;
}

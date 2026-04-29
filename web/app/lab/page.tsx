"use client";

import { useState } from "react";
import useSWR from "swr";

import { cn, fetcher, formatUsd } from "@/lib/utils";

type StrategyInfo = { name: string; edge_class: string | null; module_path: string };
type Job = {
  job_id: string;
  strategy_name: string;
  config_id: string;
  status: string;
  submitted_at: string;
  started_at: string | null;
  finished_at: string | null;
  range_start: string;
  range_end: string;
  error: string | null;
  result: null | {
    run_id: string;
    signals: number;
    fills: number;
    trades: number;
    realized_pnl: string;
    metrics: Record<string, { value: number }>;
  };
};

const PRESETS = [
  { name: "Test at 100ms latency", overrides: { latency_ms: 100 } },
  { name: "Test at 500ms latency", overrides: { latency_ms: 500 } },
  { name: "Test at 2x size", overrides: { size_multiplier: 2 } },
  { name: "Test with 0% haircut", overrides: { haircut_override: 0 } },
];

export default function StrategyLabPage() {
  const { data: strategiesResp } = useSWR<{ strategies: StrategyInfo[] }>(
    "/api/backend/analytics/strategies",
    fetcher,
  );
  const { data: jobsResp, mutate: refetchJobs } = useSWR<{ jobs: Job[] }>(
    "/api/backend/replay/jobs",
    fetcher,
    { refreshInterval: 5_000 },
  );

  const [strategy, setStrategy] = useState<string>("");
  const [days, setDays] = useState(30);
  const [overrideJson, setOverrideJson] = useState("{}");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(extraOverrides: Record<string, unknown> = {}) {
    if (!strategy) return;
    setSubmitting(true);
    setError(null);
    try {
      let overrides: Record<string, unknown> = {};
      try {
        overrides = JSON.parse(overrideJson || "{}");
      } catch {
        setError("overrides must be valid JSON");
        setSubmitting(false);
        return;
      }
      overrides = { ...overrides, ...extraOverrides };
      const resp = await fetch("/api/backend/replay/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ strategy_name: strategy, config_id: "default", days, overrides }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      await refetchJobs();
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Strategy Lab</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Replay any strategy against recorded events. Apply overrides to ask "what if".
        </p>
      </div>

      <section className="space-y-4 rounded-lg border border-border/60 bg-card p-6">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <label className="text-[10px] uppercase tracking-wider text-muted-foreground">Strategy</label>
            <select
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            >
              <option value="">— select —</option>
              {(strategiesResp?.strategies ?? []).map((s) => (
                <option key={s.name} value={s.name}>{s.name} {s.edge_class ? `· ${s.edge_class}` : ""}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[10px] uppercase tracking-wider text-muted-foreground">Days back</label>
            <input
              type="number"
              min={1}
              max={365}
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Overrides (JSON)
            </label>
            <input
              value={overrideJson}
              onChange={(e) => setOverrideJson(e.target.value)}
              placeholder='{"latency_ms": 100}'
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-xs"
            />
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            disabled={!strategy || submitting}
            onClick={() => submit()}
            className="rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background hover:opacity-90 disabled:opacity-40"
          >
            Run replay
          </button>
          <span className="text-xs text-muted-foreground self-center">— or one-click presets:</span>
          {PRESETS.map((p) => (
            <button
              key={p.name}
              disabled={!strategy || submitting}
              onClick={() => submit(p.overrides)}
              className="rounded-md border border-border bg-card px-3 py-1.5 text-xs hover:bg-accent disabled:opacity-40"
            >
              {p.name}
            </button>
          ))}
        </div>
        {error && <div className="text-xs text-loss">{error}</div>}
      </section>

      <section>
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">Recent replay jobs</h2>
        <div className="overflow-hidden rounded-lg border border-border/60">
          <table className="w-full text-xs">
            <thead className="bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left">Submitted</th>
                <th className="px-3 py-2 text-left">Strategy</th>
                <th className="px-3 py-2 text-left">Window</th>
                <th className="px-3 py-2 text-left">Status</th>
                <th className="px-3 py-2 text-right">Trades</th>
                <th className="px-3 py-2 text-right">Realized</th>
              </tr>
            </thead>
            <tbody>
              {(jobsResp?.jobs ?? []).map((j) => (
                <tr key={j.job_id} className="border-t border-border/40">
                  <td className="px-3 py-2 text-muted-foreground">{new Date(j.submitted_at).toLocaleString()}</td>
                  <td className="px-3 py-2">{j.strategy_name}</td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {new Date(j.range_start).toLocaleDateString()} → {new Date(j.range_end).toLocaleDateString()}
                  </td>
                  <td className={cn(
                    "px-3 py-2",
                    j.status === "finished" ? "text-profit" : j.status === "failed" ? "text-loss" : "text-muted-foreground",
                  )}>
                    {j.status}
                  </td>
                  <td className="px-3 py-2 text-right font-mono">{j.result?.trades ?? "—"}</td>
                  <td className="px-3 py-2 text-right font-mono">
                    {j.result ? formatUsd(Number(j.result.realized_pnl), { sign: true }) : "—"}
                  </td>
                </tr>
              ))}
              {(jobsResp?.jobs ?? []).length === 0 && (
                <tr><td colSpan={6} className="px-3 py-6 text-center text-muted-foreground">No replay jobs yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

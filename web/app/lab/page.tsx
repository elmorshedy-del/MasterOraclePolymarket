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
  { name: "100ms latency",  overrides: { latency_ms: 100 },      accent: "sky" },
  { name: "500ms latency",  overrides: { latency_ms: 500 },      accent: "amber" },
  { name: "2× size",        overrides: { size_multiplier: 2 },   accent: "highlight" },
  { name: "0% haircut",     overrides: { haircut_override: 0 },  accent: "profit" },
] as const;

const STATUS_CLS: Record<string, string> = {
  finished: "text-profit",
  failed:   "text-loss",
  running:  "text-amber-400",
  pending:  "text-muted-foreground",
};

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
  const [configId, setConfigId] = useState<string>("default");
  const [days, setDays] = useState(30);
  const [overrideJson, setOverrideJson] = useState("{}");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: sleevesResp } = useSWR<{ sleeves: { sleeve_id: string; strategy_name: string; config_id: string }[] }>(
    "/api/backend/system/sleeves",
    fetcher,
  );
  const matchingSleeves = (sleevesResp?.sleeves ?? []).filter((s) => s.strategy_name === strategy);
  const availableConfigs = Array.from(
    new Set(["default", ...matchingSleeves.map((s) => s.config_id)]),
  );

  async function submit(extraOverrides: Record<string, unknown> = {}) {
    if (!strategy) return;
    setSubmitting(true);
    setError(null);
    try {
      let overrides: Record<string, unknown> = {};
      try {
        overrides = JSON.parse(overrideJson || "{}");
      } catch {
        setError("Overrides must be valid JSON");
        setSubmitting(false);
        return;
      }
      overrides = { ...overrides, ...extraOverrides };
      const resp = await fetch("/api/backend/replay/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ strategy_name: strategy, config_id: configId, days, overrides }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      await refetchJobs();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  const jobs = jobsResp?.jobs ?? [];

  return (
    <div className="space-y-10">

      {/* Hero */}
      <section>
        <h1 className="text-[2rem] font-bold tracking-tight">Strategy Lab</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Replay any strategy against recorded events. Apply overrides to ask &ldquo;what if&rdquo;.
        </p>
      </section>

      {/* Run form */}
      <section className="space-y-5 rounded-xl border border-border/60 bg-card p-6">
        <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/70">
          Configure replay
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <FormField label="Strategy">
            <select
              value={strategy}
              onChange={(e) => { setStrategy(e.target.value); setConfigId("default"); }}
              className="w-full cursor-pointer rounded-xl border border-border bg-background px-3 py-2 text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="">— select —</option>
              {(strategiesResp?.strategies ?? []).map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name}{s.edge_class ? ` · ${s.edge_class}` : ""}
                </option>
              ))}
            </select>
          </FormField>

          <FormField label="Config">
            <select
              value={configId}
              onChange={(e) => setConfigId(e.target.value)}
              disabled={!strategy}
              className="w-full cursor-pointer rounded-xl border border-border bg-background px-3 py-2 text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-40"
            >
              {availableConfigs.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </FormField>

          <FormField label="Days back">
            <input
              type="number"
              min={1}
              max={365}
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="w-full rounded-xl border border-border bg-background px-3 py-2 text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </FormField>

          <FormField label="Overrides (JSON)">
            <input
              value={overrideJson}
              onChange={(e) => setOverrideJson(e.target.value)}
              placeholder='{"latency_ms": 100}'
              className="w-full rounded-xl border border-border bg-background px-3 py-2 font-mono text-xs transition-colors focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </FormField>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-border/40 pt-4">
          <button
            disabled={!strategy || submitting}
            onClick={() => submit()}
            className="cursor-pointer rounded-xl bg-foreground px-5 py-2 text-sm font-semibold text-background transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {submitting ? "Running…" : "Run replay"}
          </button>

          <div className="mx-1 hidden text-[10px] font-bold uppercase tracking-widest text-muted-foreground/50 sm:block">or preset</div>

          {PRESETS.map((p) => (
            <button
              key={p.name}
              disabled={!strategy || submitting}
              onClick={() => submit(p.overrides)}
              className="cursor-pointer rounded-xl border border-border bg-card px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
            >
              {p.name}
            </button>
          ))}
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-loss/30 bg-loss/10 px-3 py-2 text-xs text-loss">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
              <circle cx="6" cy="6" r="5" />
              <path d="M6 4v2.5M6 8h.01" />
            </svg>
            {error}
          </div>
        )}
      </section>

      {/* Jobs table */}
      <section className="space-y-3">
        <div>
          <h2 className="text-sm font-semibold tracking-tight">Recent Replay Jobs</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">Auto-refreshes every 5s</p>
        </div>

        <div className="overflow-hidden rounded-xl border border-border/60">
          <table className="w-full text-sm">
            <thead className="border-b border-border/60 bg-muted/30 text-[10px] font-bold uppercase tracking-widest text-muted-foreground/70">
              <tr>
                <th className="px-4 py-3 text-left">Submitted</th>
                <th className="px-4 py-3 text-left">Strategy</th>
                <th className="px-4 py-3 text-left">Window</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-right">Trades</th>
                <th className="px-4 py-3 text-right">Realized P&L</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.job_id} className="border-t border-border/40 hover:bg-muted/20">
                  <td className="px-4 py-2.5 text-xs text-muted-foreground">
                    {new Date(j.submitted_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="font-medium">{j.strategy_name}</div>
                    <div className="text-xs text-muted-foreground/70">{j.config_id}</div>
                  </td>
                  <td className="px-4 py-2.5 text-xs text-muted-foreground">
                    {new Date(j.range_start).toLocaleDateString()} → {new Date(j.range_end).toLocaleDateString()}
                  </td>
                  <td className={cn("px-4 py-2.5 font-mono text-xs font-semibold uppercase tracking-wide", STATUS_CLS[j.status] ?? "text-muted-foreground")}>
                    {j.status}
                    {j.status === "running" && (
                      <span
                        className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-amber-400"
                        style={{ animation: "pulse-dot 2s ease-in-out infinite" }}
                      />
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono">{j.result?.trades ?? "—"}</td>
                  <td className="px-4 py-2.5 text-right font-mono">
                    {j.result ? formatUsd(Number(j.result.realized_pnl), { sign: true }) : "—"}
                  </td>
                </tr>
              ))}
              {jobs.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-sm text-muted-foreground/60">
                    No replay jobs yet. Configure a run above.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="space-y-1.5">
      <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/70">{label}</div>
      {children}
    </label>
  );
}

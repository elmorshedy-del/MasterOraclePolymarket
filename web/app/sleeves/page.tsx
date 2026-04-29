import { SleevesTable } from "@/components/SleevesTable";

export default function SleevesPage() {
  return (
    <div className="space-y-6">
      <section>
        <h1 className="text-2xl font-semibold tracking-tight">Sleeves</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          One row per running sleeve. Click into a sleeve for its scorecard, equity curve, and trades.
        </p>
      </section>
      <SleevesTable />
    </div>
  );
}

import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { HAIRCUT_DEFAULT_PCT, PHASE_LABEL, VERSION } from "@/lib/version";
import { MobileNav } from "@/components/MobileNav";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Paper Trade Lab",
  description: "Research platform for prediction-market strategies",
};

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/sleeves", label: "Sleeves" },
  { href: "/matrix", label: "Matrix" },
  { href: "/trades", label: "Trades" },
  { href: "/failures", label: "Failures" },
  { href: "/lab", label: "Strategy Lab" },
];

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${inter.variable} dark`} suppressHydrationWarning>
      <body className="min-h-screen bg-background font-sans antialiased">
        <div className="flex min-h-screen flex-col">
          <header className="border-b border-border/60">
            <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-4 sm:px-6">
              <div className="flex min-w-0 items-center gap-3">
                <div className="h-7 w-7 shrink-0 rounded-md bg-gradient-to-br from-emerald-400/80 to-sky-500/80" />
                <span className="truncate text-sm font-semibold tracking-tight text-foreground">
                  Paper Trade Lab
                </span>
                <span className="hidden rounded-full border border-border/60 px-2 py-0.5 text-[10px] uppercase tracking-wider text-muted-foreground sm:inline-block">
                  {PHASE_LABEL}
                </span>
              </div>
              {/* Desktop nav — collapses to MobileNav drawer at md and below */}
              <nav className="hidden items-center gap-6 text-sm text-muted-foreground md:flex">
                {NAV.map((n) => (
                  <a key={n.href} className="hover:text-foreground transition-colors" href={n.href}>
                    {n.label}
                  </a>
                ))}
              </nav>
              <MobileNav items={NAV} />
            </div>
          </header>
          <main className="flex-1">
            <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 sm:py-8">{children}</div>
          </main>
          <footer className="border-t border-border/60 px-4 py-4 text-xs text-muted-foreground sm:px-6">
            <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2">
              <span>master-paper-trade-lab</span>
              <span className="font-mono">
                v{VERSION} · −{HAIRCUT_DEFAULT_PCT}% realism haircut
              </span>
            </div>
          </footer>
        </div>
      </body>
    </html>
  );
}

import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import { MobileNav } from "@/components/MobileNav";
import { NavLinks } from "@/components/NavLinks";
import { HAIRCUT_DEFAULT_PCT, PHASE_LABEL, VERSION } from "@/lib/version";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
  weight: ["400", "500", "600"],
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

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetbrainsMono.variable} dark`}
      suppressHydrationWarning
    >
      <body className="min-h-screen bg-background font-sans antialiased">
        <div className="flex min-h-screen flex-col">
          <header className="sticky top-0 z-30 border-b border-border/60 bg-background/85 backdrop-blur-md">
            {/* Accent gradient line */}
            <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-highlight/40 to-transparent" />
            <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
              <div className="flex min-w-0 items-center gap-3">
                <FlaskLogo />
                <span className="truncate text-sm font-semibold tracking-tight text-foreground">
                  Paper Trade Lab
                </span>
                <span className="hidden rounded-full border border-border/60 px-2 py-0.5 text-[10px] uppercase tracking-wider text-muted-foreground sm:inline-block">
                  {PHASE_LABEL}
                </span>
              </div>
              <NavLinks items={NAV} />
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

function FlaskLogo() {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 22 22"
      fill="none"
      aria-hidden="true"
      className="shrink-0"
    >
      <path
        d="M8 2.5h6M8 2.5v6L4.5 15C3.7 16.4 3.4 18.2 5.5 19.8 6.8 20.7 8.6 21 11 21s4.2-.3 5.5-1.2c2.1-1.6 1.8-3.4 1-4.8L14 8.5V2.5"
        stroke="url(#flask-grad)"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="8.5" cy="15.5" r="1" fill="hsl(158, 65%, 52%)" />
      <circle cx="13.5" cy="17.5" r="1.25" fill="hsl(243, 75%, 65%)" opacity="0.9" />
      <defs>
        <linearGradient id="flask-grad" x1="11" y1="2.5" x2="11" y2="21" gradientUnits="userSpaceOnUse">
          <stop stopColor="hsl(158, 65%, 52%)" />
          <stop offset="1" stopColor="hsl(217, 91%, 65%)" />
        </linearGradient>
      </defs>
    </svg>
  );
}

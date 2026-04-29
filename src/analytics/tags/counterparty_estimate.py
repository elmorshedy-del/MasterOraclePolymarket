"""Tag: counterparty_estimate — best guess at who took the other side.

V1 buckets: unknown / retail / sharp.

The "sharp" determination compares the counterparty wallet (if observed in
context) against a static list of pre-identified profitable wallets. The
list is configurable via the ``ANALYTICS_SHARP_WALLETS`` env var (comma-
separated wallet addresses) and seeded with a small starter list.

Phase 5+ replaces the static list with a dynamic Sharp-Wallet model trained
on observed activity-feed data (one of our deferred record-only strategies).
"""

from __future__ import annotations

import os
from typing import Any

from src.core.events import Trade


def _seed_wallets() -> set[str]:
    raw = os.environ.get("ANALYTICS_SHARP_WALLETS", "")
    seeded = {w.strip().lower() for w in raw.split(",") if w.strip()}
    # Starter pair from scout findings
    seeded.add("coldmath".lower())
    seeded.add("henrytheatmophd".lower())
    return seeded


SHARP_WALLETS = _seed_wallets()


class CounterpartyEstimateTag:
    name: str = "counterparty_estimate"
    description: str = "unknown / retail / sharp (matched against tracked wallet list)"

    def tag_trade(self, trade: Trade, context: dict[str, Any]) -> Any:
        wallet = context.get("counterparty_wallet")
        if wallet is None:
            return "unknown"
        if str(wallet).lower() in SHARP_WALLETS:
            return "sharp"
        return "retail"


def plugin() -> CounterpartyEstimateTag:
    return CounterpartyEstimateTag()

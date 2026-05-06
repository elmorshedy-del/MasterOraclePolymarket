"""Helper for clearing per-market active-position state on resolution.

Strategies maintain their own active-position bookkeeping in ``state``
under conventional keys. Listed here in one place so the runner can clear
them all at once when MARKET_RESOLVED fires for a market.

Adding a new strategy that introduces a new active-state key? Add the key
to ACTIVE_STATE_KEYS below — that's all.
"""

from __future__ import annotations

from typing import Any

# Active-state keys used by shipped strategies.
# Each entry is the dict key inside ``state`` plus a short tag describing
# how the value is shaped. The clearer handles all common shapes.
ACTIVE_STATE_KEYS: tuple[str, ...] = (
    "active_arbs",         # cross_outcome_arb, basket_arb — set[market_id]
    "_active_snipes",      # redemption_sniper            — set[(market_id, asset_id)]
    "_active_tails",       # weather_tail_sell            — set[(market_id, asset_id)]
    "_active_buys",        # weather_tail_buy             — set[(market_id, asset_id)]
    "_active_fades",       # mean_revert_post_spike       — set[market_id]
    "_active_mom",         # momentum_orderbook           — set[(market_id, asset_id)]
    "_active_orders",      # maker_passive                — set[(market_id, asset_id, side)]
    "_active_copies",      # whale_copy_eod               — set[(wallet, market_id)]
)


def clear_for_market(state: dict[str, Any], market_id: str) -> int:
    """Remove every entry in known active-state keys that refers to market_id.

    Scans EVERY position in tuple entries (not just index 0) so strategies
    that key by (wallet, market_id) — like whale_copy_eod — also get cleared.

    Returns the number of entries removed.
    """
    removed = 0
    for key in ACTIVE_STATE_KEYS:
        bag = state.get(key)
        if not isinstance(bag, set):
            continue

        to_remove: list[Any] = []
        for entry in bag:
            if entry == market_id or (isinstance(entry, tuple) and market_id in entry):
                to_remove.append(entry)

        for entry in to_remove:
            bag.discard(entry)
            removed += 1
    return removed

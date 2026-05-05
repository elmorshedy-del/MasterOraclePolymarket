"""Robust parsing helpers for strategy code paths.

Centralizes the "any input could be missing or malformed" patterns so we don't
re-invent a fragile try/except in every strategy.

Decimal pitfall: ``Decimal(str(None))`` raises ``decimal.InvalidOperation``,
NOT ``ValueError`` or ``TypeError``, so the obvious-looking guard misses it.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def safe_decimal(raw: Any) -> Decimal | None:
    """Parse to Decimal; return None if value is missing or malformed.

    Catches InvalidOperation, TypeError, and ValueError. Use this anywhere
    you'd otherwise write ``Decimal(str(payload.get(...)))`` inside a
    strategy hot path — production payloads will surprise you.
    """
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None


def safe_decimal_pair(raw: dict | None, *keys: str) -> tuple[Decimal | None, ...]:
    """Pull and parse multiple keys at once. Returns a tuple of len(keys);
    each element is None if missing/malformed. Useful for ``price/size`` pairs.
    """
    out: list[Decimal | None] = []
    if raw is None:
        return tuple([None] * len(keys))
    for k in keys:
        out.append(safe_decimal(raw.get(k)))
    return tuple(out)

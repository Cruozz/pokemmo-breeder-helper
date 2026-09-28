"""Inventory display order only; never reorder the planner's inventory input."""
from __future__ import annotations

from models import Monster


def sorted_inventory_ids(items: list[Monster], accounts: list[str]) -> list[str]:
    account_names = list(dict.fromkeys([*accounts, *(item.account for item in items)]))
    ranks = {name: index for index, name in enumerate(account_names)}

    def key(item: Monster) -> tuple[int, int, int, int]:
        try:
            page, slot = int(item.page), int(item.slot)
            if page < 1 or slot < 1:
                raise ValueError
        except (TypeError, ValueError):
            return ranks[item.account], 1, 0, 0
        # A linear slot already runs row first, then column (10 columns/row).
        return ranks[item.account], 0, page, slot

    return [item.id for item in sorted(items, key=key)]


def inventory_in_display_order(items: list[Monster], record_ids: list[str]) -> list[Monster]:
    """Keep a manual snapshot, appending new records until the next explicit sort."""
    ranks = {identifier: index for index, identifier in enumerate(record_ids)}
    return sorted(items, key=lambda item: ranks.get(item.id, len(ranks)))

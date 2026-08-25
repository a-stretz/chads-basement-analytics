from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ManagerState:
    manager: str
    budget_remaining: int = 200
    roster: list[dict] = field(default_factory=list)

    def buy(self, player: str, position: str, price: int) -> None:
        if price > self.budget_remaining:
            raise ValueError(f"{self.manager} cannot afford {price}")
        self.budget_remaining -= price
        self.roster.append({"player": player, "position": position, "price": price})

    @property
    def roster_slots_remaining(self) -> int:
        return max(0, 16 - len(self.roster))

    @property
    def max_bid(self) -> int:
        reserve = max(0, self.roster_slots_remaining - 1)
        return max(0, self.budget_remaining - reserve)

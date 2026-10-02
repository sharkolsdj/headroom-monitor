"""Stress scenario: load shocks from config/stress.yaml and apply them."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ._behaviour import SimpleBehaviour, PaymentBehaviourModel


def load_shocks(config_path: Path | None = None) -> list[dict]:
    """Load shock list from config/stress.yaml."""
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config" / "stress.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return cfg.get("shocks", [])


def resolve_largest_customer(open_ar: list[dict]) -> str | None:
    """Return the cust_code with the largest total outstanding AR amount."""
    totals: dict[str, float] = {}
    for inv in open_ar:
        code = inv["cust_code"]
        totals[code] = totals.get(code, 0.0) + float(inv.get("outstanding_amount", 0.0))
    return max(totals, key=lambda k: totals[k]) if totals else None


class StressBehaviour:
    """
    Wraps a base behaviour and adds extra delay days per customer/segment.
    customer_default codes are tracked so the caller can filter those invoices.
    """

    def __init__(
        self,
        base: PaymentBehaviourModel,
        shocks: list[dict],
        open_ar: list[dict],
    ) -> None:
        self._base = base
        self._extra_delay: dict[str, float] = {}   # cust_code -> extra days
        self._seg_extra:   dict[str, float] = {}   # segment   -> extra days
        self.defaulted_customers: set[str] = set()

        largest = resolve_largest_customer(open_ar)

        for shock in shocks:
            stype = shock.get("type")
            if stype == "customer_delay":
                code = shock["code"]
                if code == "__largest__":
                    code = largest or ""
                if code:
                    self._extra_delay[code] = (
                        self._extra_delay.get(code, 0.0) + float(shock["extra_days"])
                    )
            elif stype == "segment_delay":
                seg = shock["segment"]
                self._seg_extra[seg] = (
                    self._seg_extra.get(seg, 0.0) + float(shock["extra_days"])
                )
            elif stype == "customer_default":
                code = shock["code"]
                if code == "__largest__":
                    code = largest or ""
                if code:
                    self.defaulted_customers.add(code)

    def _extra(self, cust_code: str) -> float:
        seg = self._base.source(cust_code)   # "customer" or "segment"
        # segment string for the customer
        seg_name = ""
        # Use a duck-typing approach to get the segment name
        if hasattr(self._base, "_cust_seg"):
            seg_name = self._base._cust_seg.get(cust_code, "")  # type: ignore[attr-defined]
        return self._extra_delay.get(cust_code, 0.0) + self._seg_extra.get(seg_name, 0.0)

    def expected_delay(self, cust_code: str) -> float:
        return self._base.expected_delay(cust_code) + self._extra(cust_code)

    def delay_sample(self, cust_code: str) -> list[float]:
        extra = self._extra(cust_code)
        return [d + extra for d in self._base.delay_sample(cust_code)]

    def source(self, cust_code: str) -> str:
        return self._base.source(cust_code)

    def segment_expected_delay(self, segment: str) -> float:
        return self._base.segment_expected_delay(segment) + self._seg_extra.get(segment, 0.0)

    def conditional_remaining_delay(self, cust_code: str, d: float) -> float:
        extra = self._extra(cust_code)
        # Shift the base sample by extra before applying the conditional formula
        base_sample = self._base.delay_sample(cust_code)
        shifted = [x + extra for x in base_sample]
        qualifying = [x - d for x in shifted if x > d]
        if qualifying:
            return max(1.0, sum(qualifying) / len(qualifying))
        return max(1.0, self._base.conditional_remaining_delay(cust_code, d) + extra)


def filter_defaulted_open_ar(open_ar: list[dict], defaulted: set[str]) -> list[dict]:
    """Remove all open AR invoices for defaulted customers."""
    return [inv for inv in open_ar if inv["cust_code"] not in defaulted]

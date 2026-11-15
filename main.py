#!/usr/bin/env python3
"""Causal momentum strategy for agent-fun/bars-replay/v1; paper orders only."""
import json
import sys
from collections import deque


class Strategy:
    LOOKBACK = 20
    ENTRY_BPS = 100
    EXIT_BPS = -20
    ALLOCATION_BPS = 9000
    IMPACT_BPS = 20
    STOP_BPS = 100
    TRAIL_BPS = 100
    TRAIL_ACTIVATE_BPS = 80
    HOLD_BARS = 360
    COOLDOWN_BARS = 30

    def __init__(self, hello):
        if hello["protocol"] != "agent-fun/bars-replay/v1":
            raise ValueError("unsupported protocol")
        spec = next((s for s in hello["symbols"] if s["symbol"] == "CBBTC"), hello["symbols"][0])
        self.symbol = spec["symbol"]
        self.price_scale = spec["price_scale"]
        self.qty_scale = spec["qty_scale"]
        self.quote_scale = hello["capital"]["quote_scale"]
        self.minimum = int(hello["fees"]["min_notional_quote_units"])
        self.weight_bps = min(hello["caps"]["max_weight_bps"], self.ALLOCATION_BPS)
        self.warmup_bars = hello.get("warmup_bars", 0)
        self.history = deque(maxlen=self.LOOKBACK + 1)
        self.observed = 0
        self.held = False
        self.entry_price = 0
        self.highest = 0
        self.opened = 0
        self.cooldown_until = 0
        self.peak_equity = int(hello["capital"]["quote_units"])
        self.halted = False

    def reply(self, message):
        reply = {"type": "reply", "seq": message["seq"], "orders": []}
        bar = next((b for b in message["bars"] if b["symbol"] == self.symbol), None)
        if bar is None:
            return reply
        price = int(bar["c"])
        if price <= 0:
            return reply
        self.observed += 1
        self.history.append(price)
        account = message["account"]
        equity = int(account["equity_quote_units"])
        self.peak_equity = max(self.peak_equity, equity)
        self.halted = self.halted or equity * 10000 <= self.peak_equity * 8500
        position = next((p for p in account["positions"] if p["symbol"] == self.symbol and int(p["qty"]) > 0), None)
        if position is not None and not self.held:
            # The account confirms the fill; its bar's open is the unslipped reference.
            bought = any(f["symbol"] == self.symbol and f["side"] == "buy" and f["status"] == "filled" for f in message["fills"])
            qty = int(position["qty"])
            cost = int(position["cost_quote_units"])
            fallback = cost * 10 ** (self.price_scale + self.qty_scale) // (qty * 10 ** self.quote_scale)
            self.entry_price = int(bar["o"]) if bought else fallback
            self.highest = max(self.entry_price, price)
            self.opened = self.observed
            self.held = True
        elif position is None and self.held:
            self.held = False
            self.cooldown_until = self.observed + self.COOLDOWN_BARS
        history = list(self.history)
        reference = history[0] if len(history) == self.LOOKBACK + 1 else None
        if position is not None:
            self.highest = max(self.highest, price)
            stop = price * 10000 <= self.entry_price * (10000 - self.STOP_BPS)
            weak = reference is not None and price * 10000 < reference * (10000 + self.EXIT_BPS)
            trail_active = self.highest * 10000 >= self.entry_price * (10000 + self.TRAIL_ACTIVATE_BPS)
            trailing = trail_active and price * 10000 <= self.highest * (10000 - self.TRAIL_BPS)
            stale = self.observed - self.opened >= self.HOLD_BARS
            if self.halted or stop or weak or trailing or stale:
                reply["orders"].append({"side": "sell", "client_id": "exit-" + str(message["seq"]),
                                        "symbol": self.symbol, "qty": position["qty"], "max_slippage_bps": 100})
            return reply
        if self.halted or reference is None or message["seq"] < self.warmup_bars or self.observed < self.cooldown_until:
            return reply
        trend = price * 10000 >= reference * (10000 + self.ENTRY_BPS)
        recent_up = price > history[-6]
        if not trend or not recent_up:
            return reply
        cash = int(account["cash_quote_units"])
        equity = int(account["equity_quote_units"])
        depth = [int(d) for d in bar["c_depth"]]
        if not depth or min(depth) <= 0:
            return reply
        # For two-hop paths, D_eff = 1/(1/D1 + 1/D2), evaluated as integers.
        effective_depth = depth[0]
        for d in depth[1:]:
            effective_depth = effective_depth * d // (effective_depth + d)
        spend = min(cash * self.ALLOCATION_BPS // 10000,
                    equity * self.weight_bps // 10000,
                    effective_depth * self.IMPACT_BPS // 10000)
        if spend >= self.minimum:
            reply["orders"].append({"side": "buy", "client_id": "momentum-" + str(message["seq"]),
                                    "symbol": self.symbol, "notional_quote_units": str(spend), "max_slippage_bps": 100})
        return reply


def main():
    strategy = None
    for line in sys.stdin:
        if not line.strip():
            continue
        message = json.loads(line)
        kind = message.get("type")
        if kind == "done":
            return
        if kind == "hello":
            strategy = Strategy(message)
        elif kind == "batch":
            if strategy is None:
                raise ValueError("hello must precede batches")
            print(json.dumps(strategy.reply(message), separators=(",", ":")), flush=True)
        else:
            raise ValueError("unknown harness message")


if __name__ == "__main__":
    main()

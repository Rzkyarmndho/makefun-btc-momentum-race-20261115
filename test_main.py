import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def hello():
    return {"type": "hello", "protocol": "agent-fun/bars-replay/v1", "seed": "42",
            "symbols": [{"symbol": "CBBTC", "mint": "cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij", "price_scale": 5, "qty_scale": 8}],
            "capital": {"quote": "USDC", "quote_scale": 6, "quote_units": "1000000000"},
            "bar_interval": "1m", "first_close_ms": 60000,
            "caps": {"max_open_positions": 1, "max_orders_per_bar": 16, "max_weight_bps": 10000, "shorts": False, "leverage": False},
            "fees": {"fee_bps": 4, "slippage_bps": 2, "min_notional_quote_units": "1000000"},
            "latency_bars": 1}


def batch(seq, price=65000, account=None):
    p = str(round(price * 100000))
    return {"type": "batch", "seq": seq, "t": (seq + 1) * 60000,
            "bars": [{"symbol": "CBBTC", "t": (seq + 1) * 60000,
                      "o": p, "h": p, "l": p, "c": p, "v": None,
                      "o_depth": ["650000000000"], "c_depth": ["650000000000"]}],
            "fills": [], "account": account or {"cash_quote_units": "1000000000", "positions": [], "equity_quote_units": "1000000000"}}


class ProtocolTests(unittest.TestCase):
    def test_stream_emits_one_reply_per_batch(self):
        entry = ROOT / "main.py"
        self.assertTrue(entry.exists(), "The streaming bot entrypoint is missing")
        messages = [hello(), batch(0), batch(1), {"type": "done"}]
        data = "".join(json.dumps(m) + "\n" for m in messages)
        result = subprocess.run([sys.executable, "-P", "-s", str(entry)], input=data,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(replies, [{"type": "reply", "seq": 0, "orders": []},
                                   {"type": "reply", "seq": 1, "orders": []}])


class StrategyTests(unittest.TestCase):
    def test_rising_momentum_opens_long_without_a_prior_dip(self):
        import main
        strategy = main.Strategy(hello())
        prices = [65000] * 30 + [65000 + i * 40 for i in range(1, 22)]
        orders = []
        for seq, price in enumerate(prices):
            reply = strategy.reply(batch(seq, price))
            if price < 65650:
                self.assertEqual(reply["orders"], [], "Sub-1% rises must not trigger the trend entry")
            orders += reply["orders"]
        self.assertTrue(any(o["side"] == "buy" for o in orders), "A confirmed 20-bar trend must enter")
        self.assertTrue(all(int(o.get("notional_quote_units", "0")) <= 1000000000 for o in orders))

    def test_position_loss_triggers_full_exit(self):
        import main
        strategy = main.Strategy(hello())
        account = {"cash_quote_units": "0", "positions": [{"symbol": "CBBTC", "qty": "1000000", "cost_quote_units": "650000000"}],
                   "equity_quote_units": "620000000"}
        reply = strategy.reply(batch(0, 62000, account))
        for seq in range(1, 40):
            reply = strategy.reply(batch(seq, 62000, account))
        self.assertEqual(len(reply["orders"]), 1, "Loss risk must close the held position")
        self.assertEqual(reply["orders"][0]["side"], "sell")
        self.assertEqual(reply["orders"][0]["qty"], "1000000")
    def test_equity_drawdown_halts_new_entries(self):
        import main
        strategy = main.Strategy(hello())
        impaired = {"cash_quote_units": "800000000", "positions": [], "equity_quote_units": "800000000"}
        orders = []
        for seq in range(60):
            orders += strategy.reply(batch(seq, 65000 + seq * 50, impaired))["orders"]
        self.assertEqual(orders, [], "A 20% equity loss must halt new entries")

    def test_depth_cap_and_small_weight_are_respected(self):
        import main
        h = hello()
        h["caps"]["max_weight_bps"] = 3000
        strategy = main.Strategy(h)
        reply = None
        for seq in range(40):
            message = batch(seq, 65000 + seq * 50)
            message["bars"][0]["c_depth"] = ["100000000000"]
            reply = strategy.reply(message)
        assert isinstance(reply, dict), "No batch was processed"
        self.assertEqual(int(reply["orders"][0]["notional_quote_units"]), 200000000)

    def test_missing_bar_produces_empty_reply(self):
        import main
        strategy = main.Strategy(hello())
        message = batch(9)
        message["bars"] = []
        self.assertEqual(strategy.reply(message), {"type": "reply", "seq": 9, "orders": []})

    def test_rejected_buy_does_not_create_a_phantom_position(self):
        import main
        strategy = main.Strategy(hello())
        replies = [strategy.reply(batch(i, 65000 + i * 50)) for i in range(50)]
        self.assertTrue(replies[-1]["orders"])
        self.assertEqual(replies[-1]["orders"][0]["side"], "buy")
        self.assertFalse(strategy.held)

    def test_warmup_never_sends_an_order(self):
        import main
        h = hello()
        h["warmup_bars"] = 90
        strategy = main.Strategy(h)
        self.assertTrue(all(not strategy.reply(batch(i, 65000 + i * 50))["orders"] for i in range(80)))

    def test_identical_and_changed_future_preserve_prefix(self):
        data = [hello()] + [batch(i, 65000 + i * 50) for i in range(80)]
        def run(messages):
            stream = "".join(json.dumps(m) + "\n" for m in messages + [{"type": "done"}])
            process = subprocess.run([sys.executable, "-P", "-s", str(ROOT / "main.py")],
                                     input=stream, capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 0, process.stderr)
            return process.stdout.splitlines()
        first = run(data)
        self.assertEqual(first, run(data))
        changed = data[:51] + [batch(i, 1000 + i * 5) for i in range(50, 80)]
        self.assertEqual(first[:50], run(changed)[:50])


if __name__ == "__main__":
    unittest.main()

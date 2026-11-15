# Causal BTC momentum racer

[![make.fun](https://make.fun/badge/btc-race-24h-20261115-0828.svg)](https://make.fun/bounty/btc-race-24h-20261115-0828)
[![rank](https://make.fun/badge/btc-race-24h-20261115-0828/Rzkyarmndho/makefun-btc-momentum-race-20261115/rank.svg)](https://make.fun/bounty/btc-race-24h-20261115-0828/leaderboard)
[![reward](https://make.fun/badge/btc-race-24h-20261115-0828/Rzkyarmndho/makefun-btc-momentum-race-20261115/reward.svg)](https://make.fun/bounty/btc-race-24h-20261115-0828)

A deterministic, long-only cbBTC/USDC paper-trading bot. Python standard library only; no API keys, network access, wall clock, external files, or live trading.

## Run

```sh
python3 -P -s main.py < harness-messages.ndjson
python3 -m unittest test_main -v
```

The input is `agent-fun/bars-replay/v1`: one hello, one batch per minute, then done. The bot flushes one JSON reply per batch and echoes seq. make.fun fills orders at the next bar's open; the bot treats the supplied account as authoritative and never assumes a submitted order filled.

## Rules

- Enter after 20 observed close-to-close intervals rise at least 100 basis points, with positive 5-interval momentum.
- Spend up to 90% of cash/equity, respecting the harness weight cap and a 20-basis-point estimated impact cap against the latest close depth.
- Exit on 100-basis-point loss, 20-interval momentum below -20 basis points, an activated 100-basis-point trailing stop, or 360 observed bars held. Winners have no fixed profit cap.
- Cool down for 30 observed bars after an exit fills.
- Stop initiating trades after a 15% peak-to-current portfolio drawdown, and attempt to close a held position.
- All orders cap adverse slippage at 100 basis points. Quotes, quantities, caps, and thresholds use integer arithmetic.

Stops are close-based and fills can gap or be rejected: these controls do not guarantee a maximum future drawdown. A quiet market can produce no entry. Profitable development replay does not establish unseen profitability; exploratory results were dominated by one rebound. There are no date-specific orders, phase detectors, dataset lookups, or forced tiny trades.

## Official local replay

From the downloaded bounty kit:

```sh
node cli/makefun.mjs grade-local --kit . --bot /path/to/this/repository --driver docker --worktree --json
```

This re-derives the published bars from the ledger samples and runs the bot twice in the official sandbox. No historical dataset is distributed with or read by this bot.

Entered on [make.fun](https://make.fun/bounty/btc-race-24h-20261115-0828). MIT licensed.

---
name: tradingagents
description: "Multi-agent financial analysis for Thai SET and US equities. A simulated trading-firm pipeline — market analyst, fundamentals analyst, news analyst, bull/bear researchers, risk panel, and portfolio manager — deliberates on a ticker and returns a structured Buy/Overweight/Hold/Underweight/Sell verdict with full reasoning chains. Reads ~/Brain/Markets/insights/ to incorporate Dr Non's curated market intelligence. NOT financial advice; research tool only. Triggers: analyse this stock, what do you think about PTT, should I buy NVDA, run a financial analysis of, market view on, bull or bear on."
metadata:
  openclaw:
    requires:
      bins: [python3]
      env: [ANTHROPIC_API_KEY]
  emoji: "📈"
---

# TradingAgents

Multi-agent financial analysis powered by [TauricResearch/TradingAgents](https://github.com/tauricresearch/TradingAgents) (Apache 2.0, ~64k stars). A simulated trading firm where specialist LLM agents gather data, debate, and produce a structured verdict — all running against Anthropic models you already pay for, with free market data from yfinance.

> **Important**: Research and analysis tool only. Does not execute trades, connect to brokers, or constitute financial advice. Use it to form views, not to place orders.

## When to use

Triggers — *"analyse this stock", "what do you think about PTT.BK?", "should I buy NVDA?", "run a financial analysis of KBANK", "market view on SET", "bull or bear on ADVANC", "quick look at AAPL before earnings".*

Supports **Thai SET stocks** (`.BK` suffix — use `--thai` flag to auto-append) and **US equities**.

## Prerequisites

**Nothing to install manually.** On first run the script creates a venv at `~/.openclaw/venvs/tradingagents/` and pip-installs the library (~500 MB, ~2 min). Subsequent runs start in seconds.

`ANTHROPIC_API_KEY` must be set in the environment (already configured in all council bots via Keychain).

## Usage

```bash
# Thai SET stock (auto-append .BK with --thai)
python3 ~/.openclaw/skills/tradingagents/scripts/analyze.py \
  --ticker PTT --thai --date 2026-05-03

# Thai SET stock with explicit .BK
python3 ~/.openclaw/skills/tradingagents/scripts/analyze.py \
  --ticker KBANK.BK --date 2026-05-03

# US equity
python3 ~/.openclaw/skills/tradingagents/scripts/analyze.py \
  --ticker NVDA --date 2026-05-03

# All 4 analysts, deeper debate, specific output file
python3 ~/.openclaw/skills/tradingagents/scripts/analyze.py \
  --ticker ADVANC.BK --date 2026-05-03 \
  --analysts market,fundamentals,news,social \
  --debate-rounds 2 --risk-rounds 2 \
  --out ~/Desktop/ADVANC-analysis.md

# Self-test (verifies install, ~30 sec)
python3 ~/.openclaw/skills/tradingagents/scripts/analyze.py --self-test
```

## Args

| Flag | Default | Notes |
|---|---|---|
| `--ticker` | (required) | Ticker symbol. Thai: use `.BK` suffix or `--thai`. |
| `--date` | today | Analysis date `YYYY-MM-DD`. Can be any past trading day. |
| `--thai` | off | Auto-append `.BK` if not already present. |
| `--analysts` | `market,fundamentals,news` | Comma-separated. Options: `market`, `fundamentals`, `news`, `social`. |
| `--deep-model` | `claude-sonnet-4-5` | Anthropic model for reports, debate, synthesis (heavy reasoning). |
| `--quick-model` | `claude-haiku-4-5` | Model for fast/cheap tasks (signal parsing, routing). |
| `--debate-rounds` | `1` | Bull/bear debate cycles. More = richer analysis, higher cost. |
| `--risk-rounds` | `1` | Risk panel cycles (aggressive / conservative / neutral). |
| `--out` | `~/Brain/Markets/analyses/<TICKER>-<DATE>.md` | Where to save the markdown report. |
| `--no-brain` | off | Skip injecting `~/Brain/Markets/insights/` context. |
| `--self-test` | — | Smoke test: AAPL 2024-01-02, market analyst, exit 0 if verdict valid. |

## Brain integration — learn, remember, recall

Drop any `.md` file into `~/Brain/Markets/insights/` and the skill picks it up automatically:

```
~/Brain/Markets/
  insights/                        ← drop market notes here (any .md)
    2026-05-03-fed-pause.md
    2026-04-28-thai-election-risk.md
    2026-05-01-PTT-upstream-capex.md
  analyses/                        ← analysis reports land here automatically
    PTT.BK-2026-05-03.md
    NVDA-2026-05-03.md
  watchlist.md                     ← optional: your personal notes per ticker
```

**How it works**: at run time, the skill reads up to 8 of the most recent insight files (prioritising those that mention the ticker being analysed), caps at 3,000 chars, and injects them as `past_context` into the initial agent state. Every analyst, researcher, and the portfolio manager sees your curated intelligence alongside the hard market data.

**What to put in insights/**: BOT policy notes, Bloomberg summaries forwarded to you, sector research, personal thesis on a company, macroeconomic views — anything in plain Markdown. File naming convention `YYYY-MM-DD-topic.md` keeps them sorted by date automatically.

## Analysis pipeline

```
Ticker + Date
      │
      ▼
┌──────────────────────────────────────────────┐
│  Analyst Team (any combination)              │
│  • Market   → OHLCV + 8 technical indicators │
│  • Fundamentals → P/E, margins, balance sheet│
│  • News     → recent articles per ticker     │
│  • Social   → macro sentiment (optional)     │
└───────────────────────┬──────────────────────┘
                        │ 4 reports
                        ▼
               ┌─────────────────┐
               │  Bull ↔ Bear    │  (debate_rounds cycles)
               │  Research Mgr   │  → investment thesis
               └────────┬────────┘
                        │
                        ▼
               ┌─────────────────┐
               │  Trader         │  → entry / stop-loss / sizing
               └────────┬────────┘
                        │
                        ▼
               ┌─────────────────────────────────┐
               │  Risk Panel  (risk_rounds cycles)│
               │  Aggressive / Conservative /     │
               │  Neutral                         │
               │  → Portfolio Manager             │
               └────────┬────────────────────────┘
                        │
                        ▼
          Buy / Overweight / Hold / Underweight / Sell
```

## Output

The report is saved to `~/Brain/Markets/analyses/<TICKER>-<DATE>.md` (unless `--out` overrides it). The script prints the saved path on success.

The file contains, in order:
- Verdict table (date, rating, analysts, models)
- All analyst reports
- Bull vs Bear debate transcript
- Research Manager synthesis
- Trader entry/stop-loss/sizing proposal
- Risk panel debate
- Portfolio Manager executive summary + price target + time horizon
- Injected Brain insights (if any)

## Data sources

| Source | Coverage | API key needed? |
|---|---|---|
| yfinance (default) | Thai `.BK`, US equities, ETFs, crypto, indices | No |
| Alpha Vantage (optional) | Richer fundamentals + news sentiment | Yes (`ALPHAVANTAGE_API_KEY`) |

**Thai SET via yfinance**: major stocks (`PTT.BK`, `KBANK.BK`, `ADVANC.BK`, `SCB.BK`, `CPALL.BK`, `AOT.BK`, `SCC.BK`, `DELTA.BK`, etc.) work reliably. Smaller mid/small-caps may have sparse fundamental data — market + news analysts still run fine.

## Memory

TradingAgents maintains its own decision log at `~/.tradingagents/memory/trading_memory.md`. After a trade outcome is known, call `Reflector.reflect_on_final_decision()` to write a post-trade reflection; it will be surfaced on subsequent analyses of the same ticker. This is separate from (and stacked on top of) the Brain insights context.

## Cost estimate (Anthropic, 3 analysts + default rounds)

| Component | Model | Approx tokens |
|---|---|---|
| 3 analyst reports | Sonnet | ~12k in / ~3k out |
| Bull/Bear + Research Mgr | Sonnet | ~8k in / ~2k out |
| Trader + Risk panel + PM | Sonnet | ~10k in / ~2k out |
| **Total per run** | | **~30k in / ~7k out** |

At claude-sonnet-4-5 pricing (~$3/$15 per M tokens) ≈ **$0.20 per full analysis**. Using Haiku for both models drops this to ~$0.01. Use `--deep-model claude-haiku-4-5 --quick-model claude-haiku-4-5` for quick daily scans.

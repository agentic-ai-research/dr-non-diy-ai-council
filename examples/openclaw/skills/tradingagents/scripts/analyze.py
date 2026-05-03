#!/usr/bin/env python3
"""
tradingagents — multi-agent financial analysis for Thai (SET) and US equities.

Wraps TauricResearch/TradingAgents v0.1.0: a simulated trading-firm pipeline
where specialist LLM agents (market analyst, fundamentals analyst, news analyst,
bull/bear researchers, risk panel, portfolio manager) deliberate on a ticker
and return a structured BUY / SELL / HOLD verdict with full reasoning chains.

Auto-installs into ~/.openclaw/venvs/tradingagents/ on first run.
Reads ~/Brain/Markets/insights/ to inject Dr Non's curated market intelligence
into every analysis — drop .md files there, they're picked up automatically.

IMPORTANT: Research and analysis tool only. Does not execute trades, connect
to brokers, or constitute financial advice.

Usage:
    python3 analyze.py --ticker PTT --thai --date 2026-05-03
    python3 analyze.py --ticker NVDA --date 2026-05-03
    python3 analyze.py --self-test
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VENV_DIR     = Path.home() / ".openclaw" / "venvs" / "tradingagents"
BRAIN_DIR    = Path.home() / "Brain" / "Markets"
INSIGHTS_DIR = BRAIN_DIR / "insights"
ANALYSES_DIR = BRAIN_DIR / "analyses"

MAX_INSIGHT_FILES = 8     # most-recent N insight files to consider
MAX_INSIGHT_CHARS = 3000  # hard cap so we don't blow context

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [tradingagents] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("tradingagents")


# ---------------------------------------------------------------------------
# Venv bootstrap — always the first thing that runs (before any heavy imports)
# ---------------------------------------------------------------------------

def _ensure_venv() -> None:
    """Create the venv and pip-install tradingagents if needed (~2 min first run)."""
    python = VENV_DIR / "bin" / "python"
    if python.exists():
        return
    log.info("First run — creating venv at %s…", VENV_DIR)
    VENV_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    pip = VENV_DIR / "bin" / "pip"
    subprocess.run([str(pip), "install", "--quiet", "--upgrade", "pip"], check=True)
    log.info("Installing tradingagents and dependencies (one-time, ~500 MB)…")
    subprocess.run([str(pip), "install", "--quiet", "tradingagents"], check=True)
    log.info("Venv ready.")


def _relaunch_in_venv() -> None:
    """Re-exec this script inside the tradingagents venv if not already there."""
    if sys.prefix == str(VENV_DIR):
        return  # already inside the right venv
    _ensure_venv()
    python = VENV_DIR / "bin" / "python"
    os.execv(str(python), [str(python)] + sys.argv)


# ---------------------------------------------------------------------------
# Ticker helpers
# ---------------------------------------------------------------------------

def normalise_ticker(ticker: str, *, thai: bool) -> str:
    """Upper-case; append .BK for Thai SET stocks when --thai is set."""
    t = ticker.upper().strip()
    if thai and not t.endswith(".BK"):
        t += ".BK"
    return t


# ---------------------------------------------------------------------------
# Brain insights loader
# ---------------------------------------------------------------------------

def load_insights(ticker: str) -> str:
    """
    Read ~/Brain/Markets/insights/*.md. Files mentioning the ticker are
    shown first, then newest-first. Caps at MAX_INSIGHT_CHARS.
    Returns empty string if the directory doesn't exist or is empty.
    """
    if not INSIGHTS_DIR.exists():
        return ""

    files = sorted(
        INSIGHTS_DIR.glob("*.md"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return ""

    stem = ticker.replace(".BK", "").lower()
    priority, rest = [], []
    for f in files:
        txt = f.read_text(encoding="utf-8", errors="ignore")
        (priority if stem in txt.lower() else rest).append((f, txt))

    ordered = (priority + rest)[:MAX_INSIGHT_FILES]

    parts: list[str] = []
    total = 0
    for f, text in ordered:
        snippet = text.strip()
        remaining = MAX_INSIGHT_CHARS - total
        if remaining <= 0:
            break
        if len(snippet) > remaining:
            snippet = snippet[:remaining] + "\n…[truncated]"
        parts.append(f"### {f.stem}\n{snippet}")
        total += len(snippet)

    if not parts:
        return ""

    return (
        "## Market Insights (curated by Dr Non Arkara — ~/Brain/Markets/insights/)\n\n"
        + "\n\n".join(parts)
    )


# ---------------------------------------------------------------------------
# Core analysis runner (only reached after venv re-exec)
# ---------------------------------------------------------------------------

def run_analysis(
    ticker: str,
    analysis_date: str,
    *,
    analysts: list[str],
    deep_model: str,
    quick_model: str,
    debate_rounds: int,
    risk_rounds: int,
    extra_context: str,
    out_file: Path | None,
) -> tuple[str, str]:
    """
    Run TradingAgentsGraph.propagate() and return (markdown_report, verdict).
    `extra_context` (Brain insights) is injected as a system message so that
    every agent in the pipeline sees it through the shared messages history.
    """
    # Late imports — only reachable after venv re-exec
    from langchain_core.messages import HumanMessage, SystemMessage  # noqa: PLC0415
    from tradingagents.default_config import TradingAgentsConfig      # noqa: PLC0415
    from tradingagents.graph.trading_graph import TradingAgentsGraph  # noqa: PLC0415

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.error("ANTHROPIC_API_KEY not set — cannot call Anthropic LLMs.")
        sys.exit(1)

    # results_dir: where TradingAgents saves its own JSON logs
    results_dir = ANALYSES_DIR / "raw"
    results_dir.mkdir(parents=True, exist_ok=True)

    cfg = TradingAgentsConfig(
        llm_provider="anthropic",
        deep_think_llm=deep_model,
        quick_think_llm=quick_model,
        max_debate_rounds=debate_rounds,
        max_risk_discuss_rounds=risk_rounds,
        max_recur_limit=25,
        results_dir=results_dir,
    )

    ta = TradingAgentsGraph(selected_analysts=analysts, config=cfg)

    # Inject Brain insights by monkey-patching create_initial_state.
    # We add a SystemMessage before the ticker HumanMessage so every agent
    # in the pipeline receives the curated context in its message history.
    if extra_context:
        original_create = ta.propagator.create_initial_state

        def _patched_create(company_name: str, trade_date: str):
            state = original_create(company_name, trade_date)
            context_msg = SystemMessage(
                content=(
                    "The following market intelligence has been curated by the analyst "
                    "overseeing this research. Use it to supplement the data you gather, "
                    "but rely primarily on the quantitative data from your tools.\n\n"
                    + extra_context
                )
            )
            # Prepend the context message before the existing messages
            state.messages = [context_msg] + list(state.messages)
            return state

        ta.propagator.create_initial_state = _patched_create
        log.info("Brain insights injected into agent context (%d chars)", len(extra_context))

    log.info("Propagating: %s @ %s  analysts=%s", ticker, analysis_date, analysts)
    final_state, verdict = ta.propagate(ticker, analysis_date)
    log.info("Verdict: %s", verdict)

    # -----------------------------------------------------------------------
    # Build markdown report from AgentState
    # -----------------------------------------------------------------------
    lines: list[str] = [
        f"# TradingAgents Analysis: {ticker}",
        "",
        "| | |",
        "|---|---|",
        f"| **Date** | {analysis_date} |",
        f"| **Verdict** | **{verdict}** |",
        f"| **Analysts** | {', '.join(analysts)} |",
        f"| **Models** | {deep_model} / {quick_model} |",
        "",
        "---",
        "",
    ]

    for attr, heading in [
        ("market_report",       "## Market Report"),
        ("sentiment_report",    "## Sentiment / Social Report"),
        ("news_report",         "## News Report"),
        ("fundamentals_report", "## Fundamentals Report"),
    ]:
        val = getattr(final_state, attr, None)
        if val and val.strip():
            lines += [heading, "", val.strip(), ""]

    debate = getattr(final_state, "investment_debate_state", None)
    if debate and getattr(debate, "history", None):
        lines += ["## Bull vs Bear Debate", "", debate.history.strip(), ""]

    plan = getattr(final_state, "investment_plan", None)
    if plan and str(plan).strip():
        lines += ["## Research Manager Synthesis", "", str(plan).strip(), ""]

    trader = getattr(final_state, "trader_investment_plan", None)
    if trader and str(trader).strip():
        lines += ["## Trader Proposal (Entry / Stop-Loss / Sizing)", "", str(trader).strip(), ""]

    risk = getattr(final_state, "risk_debate_state", None)
    if risk and getattr(risk, "history", None):
        lines += ["## Risk Panel Debate", "", risk.history.strip(), ""]

    final_decision = getattr(final_state, "final_trade_decision", None)
    if final_decision and str(final_decision).strip():
        lines += ["## Portfolio Manager Decision", "", str(final_decision).strip(), ""]

    if extra_context:
        lines += ["", "---", "", "## Context Injected from ~/Brain/Markets/insights/", "", extra_context]

    lines += [
        "",
        "---",
        "",
        "> **Disclaimer**: Generated by LLM agents for research purposes only.",
        "> Not financial advice. Do not use as the sole basis for any investment decision.",
    ]

    markdown = "\n".join(lines)

    # -----------------------------------------------------------------------
    # Save / print
    # -----------------------------------------------------------------------
    if out_file:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(markdown, encoding="utf-8")
        log.info("✓ saved → %s", out_file)
        print(out_file)
    else:
        print(markdown)

    return markdown, verdict


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def self_test() -> int:
    """Smoke test: analyse AAPL on 2024-01-02 with market analyst only."""
    log.info("Self-test: AAPL 2024-01-02, market analyst only, no Brain context")
    _, verdict = run_analysis(
        "AAPL",
        "2024-01-02",
        analysts=["market"],
        deep_model="claude-haiku-4-5",
        quick_model="claude-haiku-4-5",
        debate_rounds=1,
        risk_rounds=1,
        extra_context="",
        out_file=None,
    )
    # v0.1.0 returns BUY / SELL / HOLD
    valid = {"BUY", "SELL", "HOLD"}
    if verdict.upper() not in valid:
        log.error("self-test FAILED: unexpected verdict %r", verdict)
        return 1
    log.info("✓ self-test passed: verdict=%s", verdict)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="tradingagents",
        description="Multi-agent financial analysis (Thai SET + US equities).",
    )
    parser.add_argument("--ticker", help="Ticker symbol, e.g. AAPL or PTT.BK")
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Analysis date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--thai",
        action="store_true",
        help="Auto-append .BK suffix for Thai SET stocks",
    )
    parser.add_argument(
        "--analysts",
        default="market,fundamentals,news",
        help=(
            "Comma-separated analysts to run. "
            "Options: market, fundamentals, news, social. "
            "Default: market,fundamentals,news"
        ),
    )
    parser.add_argument(
        "--deep-model",
        default="claude-sonnet-4-5",
        help="Anthropic model for reports and debates (default: claude-sonnet-4-5)",
    )
    parser.add_argument(
        "--quick-model",
        default="claude-haiku-4-5",
        help="Anthropic model for fast/cheap tasks (default: claude-haiku-4-5)",
    )
    parser.add_argument(
        "--debate-rounds",
        type=int,
        default=1,
        help="Bull/bear debate cycles (default: 1)",
    )
    parser.add_argument(
        "--risk-rounds",
        type=int,
        default=1,
        help="Risk panel cycles (default: 1)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output .md path (default: ~/Brain/Markets/analyses/<TICKER>-<DATE>.md)",
    )
    parser.add_argument(
        "--no-brain",
        action="store_true",
        help="Skip loading ~/Brain/Markets/insights/ context",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run self-test (AAPL 2024-01-02, market analyst) and exit",
    )
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    if not args.ticker:
        parser.error("--ticker is required (or use --self-test)")

    ticker = normalise_ticker(args.ticker, thai=args.thai)

    analysts = [a.strip() for a in args.analysts.split(",") if a.strip()]
    valid_analysts = {"market", "fundamentals", "news", "social"}
    bad = set(analysts) - valid_analysts
    if bad:
        parser.error(f"Unknown analyst(s): {bad}. Choose from {valid_analysts}")

    out_file = (
        Path(args.out).expanduser()
        if args.out
        else ANALYSES_DIR / f"{ticker}-{args.date}.md"
    )

    extra_context = "" if args.no_brain else load_insights(ticker)

    run_analysis(
        ticker,
        args.date,
        analysts=analysts,
        deep_model=args.deep_model,
        quick_model=args.quick_model,
        debate_rounds=args.debate_rounds,
        risk_rounds=args.risk_rounds,
        extra_context=extra_context,
        out_file=out_file,
    )
    return 0


if __name__ == "__main__":
    _relaunch_in_venv()
    sys.exit(main())

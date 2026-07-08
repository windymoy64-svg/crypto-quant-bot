# Vibe-Trading Reference Notes

Source: https://github.com/HKUDS/Vibe-Trading

Vibe-Trading is useful as a research workspace reference. It has market-data loaders, backtest workflows, reports, CLI/Web UI, MCP support, and optional broker/live trading boundaries.

For this crypto quant bot, use it only where it strengthens the project without weakening determinism.

## Use

- Research workflow: plan, ground, execute, validate, deliver.
- Data fallback idea: OKX, ccxt, yfinance, and local files for crypto.
- Backtest artifacts: save metrics, warnings, configs, and run summaries.
- Shadow Account idea: compare actual trades against rule-based ideal behavior.
- Safety model: paper/live boundary, audit trail, kill switch, and explicit authorization.

## Do Not Use As Core

- Do not use an LLM to choose BUY or SELL.
- Do not make Vibe-Trading a required dependency for running the bot.
- Do not enable live trading before backtest, paper trading, and risk limits are stable.

## Suggested Architecture Position

```text
Vibe-Trading optional research
        |
        v
Research notes / candidate strategy ideas
        |
        v
Deterministic rule config
        |
        v
Score engine
        |
        v
JSON signal
        |
        v
Paper/live execution
```

The bridge in `app/research/vibe_trading_bridge.py` can call the local `vibe-trading` CLI when installed. It should not be imported by the execution engine.

"""Executor Agent — executes decisions to the exchange.

This agent receives a Decision from the Decision Maker and translates it
into concrete exchange orders. It handles:
- Market orders (immediate entry/exit)
- Limit orders (entry at specific price)
- Stop orders (stop loss placement)
- Position sizing based on risk

Key principles:
- Never executes without a valid Decision
- Respects existing safety guards (live trading lock, dry run, max positions)
- Logs every action for Learning Agent to consume
- Graceful fallback if exchange is unreachable
"""

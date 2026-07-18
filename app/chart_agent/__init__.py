"""Chart Reader Agent — Pure Python deterministic chart analysis engine.

Combines all available techniques (ACR+, Liquidity S/R MTF, candle patterns,
market structure, regime detection) into a single adaptive reader that selects
and weights techniques based on current market conditions.

No LLM, no ML inference — all logic is explicit and auditable.
"""

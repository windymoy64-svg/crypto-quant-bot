"""Learning Agent — records, analyzes, and extracts insights from trade history.

This agent learns from every trade result (TP, SL, trailing, hold) and builds
a knowledge base that helps the Decision Maker agent make better choices.

Key responsibilities:
1. RECORD — Store every trade with full context (chart reading, regime, patterns)
2. ANALYZE — Compute statistics per technique, pattern, regime, pair
3. EXTRACT — Produce LearningInsight that Decision Maker can consume
4. EVOLVE — Insights improve as more data accumulates

No LLM, no ML training — pure statistical learning from deterministic data.
"""

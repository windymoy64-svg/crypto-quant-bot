"""Decision Maker Agent — takes trading decisions based on chart data + learning.

This agent receives:
1. ChartReading from Chart Reader Agent (what's happening NOW)
2. LearningInsight from Learning Agent (what historically works)

And produces a Decision:
- ENTRY (BUY/SELL) with levels
- HOLD (keep position)
- EXIT (close position)
- SKIP (don't trade)

Key principles:
- Deterministic: same inputs → same output
- Learning-informed: uses historical insights to calibrate confidence
- Conservative: prefers SKIP over bad entries
- Explainable: every decision has clear reasons
"""

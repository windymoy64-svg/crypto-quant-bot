"""Chart Reader Agent — deterministic core + optional free-technique LLM proposal.

Python core combines techniques (ACR+, Liquidity S/R MTF, candle patterns,
market structure, regime detection) into an adaptive ChartReading. This core is
deterministic and auditable (same input -> same output).

Optionally, the Chart LLM (wired via the pipeline coordinator) may analyse the
market with ANY method/indicator/technique suited to the regime and the coin,
emitting a ChartProposal (see proposal.py). Proposal geometry is validated in
Python; it is advisory unless the Decision Agent adopts validated levels.
Final orders remain non-LLM (Risk + Executor).
"""

"""Multi-agent coordinator for Chart, Learning, Decision, and Executor agents.

The coordinator is the only component allowed to wire agent outputs together.
It does not contain trading logic itself; each agent keeps its own single
responsibility and auditable output schema.
"""
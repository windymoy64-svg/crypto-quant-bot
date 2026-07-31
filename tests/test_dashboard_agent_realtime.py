from pathlib import Path


def test_agent_candidates_use_cross_process_realtime_pipeline_stream() -> None:
    websocket = Path("app/dashboard/websocket.py").read_text(encoding="utf-8")
    javascript = Path("app/dashboard/static/dashboard.js").read_text(encoding="utf-8")

    assert "_broadcast_agent_pipeline_updates" in websocket
    assert "interval_seconds: float = 1.0" in websocket
    assert '"type": "agent_pipeline_update"' in websocket
    assert 'if(data.type==="agent_pipeline_update") handleAgentPipelineUpdate(data.payload)' in javascript
    assert "function handleAgentPipelineUpdate(" in javascript


def test_agent_candidate_processing_state_is_rendered_and_deduplicated() -> None:
    javascript = Path("app/dashboard/static/dashboard.js").read_text(encoding="utf-8")

    assert 'item.processing === true' in javascript
    assert 'processing ? "PROCESSING"' in javascript
    assert "Scanner passed · Chart/Decision Agent processing" in javascript
    assert ".filter(item=>String(item?.symbol" in javascript
    assert "setInterval(() => loadAgentPanels().catch(console.warn), 30000)" not in javascript
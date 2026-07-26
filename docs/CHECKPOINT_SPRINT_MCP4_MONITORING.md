# Checkpoint — Sprint MCP-4 Monitoring / Notification

## Tools

- `get_system_health` — wraps `SystemHealthMonitor.snapshot` + artifact flags
- `send_ops_notification` — TelegramNotifier; default dry-run (`live=false`)

## Safety

- No trading execution
- Live notify requires env credentials + explicit `live=true`
- Rate limit 5s between live sends
- Message max 3500 chars

## Verify

```bash
./.venv/bin/python -m pytest tests/test_mcp_ops.py -q
./.venv/bin/python -c "from app.mcp.tools import get_system_health, send_ops_notification; print(get_system_health()['ok'], send_ops_notification('hi')['note'])"
```

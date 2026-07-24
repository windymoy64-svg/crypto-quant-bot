# Scanner UI backup — pre terminal hybrid (2026-07-24)

Restore:

```bash
cp backups/scanner_ui_pre_terminal_20260724/index.html app/dashboard/templates/index.html
cp backups/scanner_ui_pre_terminal_20260724/dashboard.css app/dashboard/static/dashboard.css
cp backups/scanner_ui_pre_terminal_20260724/services.py app/dashboard/services.py
```

New UI after this backup:
- Market breadth header
- Score-first table with Price/24H/Vol/Liq
- Move Alerts panel
- Tabs All/Long/Short + sort Score/24H/Vol
- Responsive mobile card layout

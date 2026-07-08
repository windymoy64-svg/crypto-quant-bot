from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


class StrategyReportWriter:
    def __init__(self, output_dir: str | Path = "reports") -> None:
        self.output_dir = Path(output_dir)

    def write(self, report: dict[str, Any]) -> dict[str, str]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.output_dir / "strategy_report.json"
        html_path = self.output_dir / "strategy_report.html"
        csv_path = self.output_dir / "strategy_report.csv"
        json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        html_path.write_text(render_html_report(report), encoding="utf-8")
        write_csv_summary(csv_path, report)
        return {"json": str(json_path), "html": str(html_path), "csv": str(csv_path)}


def write_csv_summary(path: Path, report: dict[str, Any]) -> None:
    rows: list[dict[str, Any]] = []
    for key, value in report.get("overall_performance", {}).items():
        rows.append({"section": "overall_performance", "name": key, "metric": key, "value": value})
    for section in ("pair_analysis", "timeframe_analysis", "market_regime_analysis", "rule_attribution", "feature_importance_summary", "time_of_day_analysis", "day_of_week_analysis"):
        for item in report.get(section, []):
            name = item.get("name") or item.get("rule") or item.get("feature") or item.get("bucket") or "unknown"
            for metric, value in item.items():
                if metric in {"name", "rule", "feature", "bucket"}:
                    continue
                rows.append({"section": section, "name": name, "metric": metric, "value": value})
    for key, value in report.get("trade_duration_analysis", {}).items():
        rows.append({"section": "trade_duration_analysis", "name": key, "metric": key, "value": value})
    rows.append({"section": "streaks", "name": "longest_winning_streak", "metric": "count", "value": report.get("longest_winning_streak", 0)})
    rows.append({"section": "streaks", "name": "longest_losing_streak", "metric": "count", "value": report.get("longest_losing_streak", 0)})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["section", "name", "metric", "value"])
        writer.writeheader()
        writer.writerows(rows)


def render_html_report(report: dict[str, Any]) -> str:
    payload = json.dumps(report).replace("</", "<\\/")
    title = "Strategy Validation Report"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <style>
    body {{ margin: 0; background: #0f172a; color: #e2e8f0; font-family: Georgia, 'Times New Roman', serif; }}
    header {{ padding: 28px 32px; background: linear-gradient(135deg, #0f172a, #164e63); }}
    h1 {{ margin: 0; font-size: 32px; }}
    main {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 18px; padding: 24px; }}
    .chart {{ min-height: 360px; border: 1px solid rgba(148, 163, 184, .22); border-radius: 18px; background: rgba(15, 23, 42, .82); }}
  </style>
</head>
<body>
  <header><h1>{title}</h1><p>Research-only artifact analysis. No trading execution.</p></header>
  <main>
    <div id="overall" class="chart"></div>
    <div id="pairs" class="chart"></div>
    <div id="timeframes" class="chart"></div>
    <div id="regimes" class="chart"></div>
    <div id="rules" class="chart"></div>
    <div id="features" class="chart"></div>
    <div id="hours" class="chart"></div>
    <div id="weekdays" class="chart"></div>
    <div id="duration" class="chart"></div>
    <div id="equity" class="chart"></div>
  </main>
  <script id="report-data" type="application/json">{payload}</script>
  <script>
    const report = JSON.parse(document.getElementById('report-data').textContent);
    const theme = {{ textStyle: {{ color: '#cbd5e1' }}, backgroundColor: 'transparent' }};
    function chart(id, option) {{ echarts.init(document.getElementById(id)).setOption(Object.assign({{}}, theme, option)); }}
    function names(rows, key='name') {{ return (rows || []).map(row => row[key]); }}
    function vals(rows, key) {{ return (rows || []).map(row => Number(row[key] || 0)); }}
    const overall = report.overall_performance || {{}};
    chart('overall', {{ title: {{ text: 'Overall Performance', textStyle: {{ color: '#f8fafc' }} }}, tooltip: {{}}, xAxis: {{ type: 'category', data: ['Net', 'Gross+', 'Gross-', 'PF', 'Win%'] }}, yAxis: {{ type: 'value' }}, series: [{{ type: 'bar', data: [overall.net_profit, overall.gross_profit, overall.gross_loss, overall.profit_factor, overall.win_rate] }}] }});
    chart('pairs', {{ title: {{ text: 'Pair Net Profit', textStyle: {{ color: '#f8fafc' }} }}, tooltip: {{}}, xAxis: {{ type: 'category', data: names(report.pair_analysis) }}, yAxis: {{ type: 'value' }}, series: [{{ type: 'bar', data: vals(report.pair_analysis, 'net_profit') }}] }});
    chart('timeframes', {{ title: {{ text: 'Timeframe Win Rate', textStyle: {{ color: '#f8fafc' }} }}, tooltip: {{}}, xAxis: {{ type: 'category', data: names(report.timeframe_analysis) }}, yAxis: {{ type: 'value' }}, series: [{{ type: 'bar', data: vals(report.timeframe_analysis, 'win_rate') }}] }});
    chart('regimes', {{ title: {{ text: 'Market Regime Net Profit', textStyle: {{ color: '#f8fafc' }} }}, tooltip: {{}}, xAxis: {{ type: 'category', data: names(report.market_regime_analysis) }}, yAxis: {{ type: 'value' }}, series: [{{ type: 'bar', data: vals(report.market_regime_analysis, 'net_profit') }}] }});
    chart('rules', {{ title: {{ text: 'Rule Contribution', textStyle: {{ color: '#f8fafc' }} }}, tooltip: {{}}, xAxis: {{ type: 'category', data: names(report.rule_attribution, 'rule') }}, yAxis: {{ type: 'value' }}, series: [{{ type: 'bar', data: vals(report.rule_attribution, 'contribution') }}] }});
    chart('features', {{ title: {{ text: 'Feature Importance', textStyle: {{ color: '#f8fafc' }} }}, tooltip: {{}}, xAxis: {{ type: 'category', data: names(report.feature_importance_summary, 'feature') }}, yAxis: {{ type: 'value' }}, series: [{{ type: 'bar', data: vals(report.feature_importance_summary, 'score') }}] }});
    chart('hours', {{ title: {{ text: 'Time Of Day Net Profit', textStyle: {{ color: '#f8fafc' }} }}, tooltip: {{}}, xAxis: {{ type: 'category', data: names(report.time_of_day_analysis, 'bucket') }}, yAxis: {{ type: 'value' }}, series: [{{ type: 'bar', data: vals(report.time_of_day_analysis, 'net_profit') }}] }});
    chart('weekdays', {{ title: {{ text: 'Day Of Week Win Rate', textStyle: {{ color: '#f8fafc' }} }}, tooltip: {{}}, xAxis: {{ type: 'category', data: names(report.day_of_week_analysis, 'bucket') }}, yAxis: {{ type: 'value' }}, series: [{{ type: 'bar', data: vals(report.day_of_week_analysis, 'win_rate') }}] }});
    const d = report.trade_duration_analysis || {{}};
    chart('duration', {{ title: {{ text: 'Trade Duration Seconds', textStyle: {{ color: '#f8fafc' }} }}, tooltip: {{}}, xAxis: {{ type: 'category', data: ['Avg', 'Min', 'Max'] }}, yAxis: {{ type: 'value' }}, series: [{{ type: 'bar', data: [d.average_seconds, d.min_seconds, d.max_seconds] }}] }});
    const series = (report.equity_curve_summary && report.equity_curve_summary.series) || [];
    chart('equity', {{ title: {{ text: 'Equity Curve', textStyle: {{ color: '#f8fafc' }} }}, tooltip: {{ trigger: 'axis' }}, xAxis: {{ type: 'category', data: series.map(row => row.timestamp) }}, yAxis: {{ type: 'value' }}, series: [{{ type: 'line', smooth: true, data: series.map(row => row.equity) }}] }});
  </script>
</body>
</html>
"""
"""Regresi perhitungan persentase Real-Time P&L Stream."""

from pathlib import Path


TEMPLATE = Path("app/dashboard/templates/index.html")


def test_pnl_stream_memakai_roe_terhadap_margin() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")

    assert "const storedMargin = Number(p.used_capital);" in html
    assert "const margin = Number.isFinite(storedMargin) && storedMargin > 0" in html
    assert "const roe = margin > 0" in html
    assert "? (pnlDollar / margin) * 100" in html
    assert '<div class="pnl-value">${pct(roe)}</div>' in html


def test_pnl_stream_tidak_memakai_perubahan_harga_sebagai_persentase() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")

    assert "((entry - last) / entry) * 100" not in html
    assert "((last - entry) / entry) * 100" not in html


def test_pnl_stream_margin_fallback_memperhitungkan_leverage() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")

    assert "Number(p.leverage ?? p.configured_leverage ?? 1)" in html
    assert ": notional / leverage;" in html
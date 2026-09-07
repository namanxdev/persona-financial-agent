"""Pure formatting helpers used only for rendering already-retrieved values.

Nothing here touches the network or a database; it exists so grounding.py's
claim templates stay readable. No function here can produce a number that
wasn't already on the evidence row passed in.
"""

_METRIC_LABELS: dict[str, str] = {
    "revenue_growth_yoy": "revenue growth (YoY)",
    "revenue_growth": "revenue growth",
    "price_to_sales_ttm": "price/sales (TTM)",
    "fcf_margin": "FCF margin",
    "operating_margin_ttm": "operating margin (TTM)",
    "operating_margin": "operating margin",
    "diluted_eps": "diluted EPS",
    "trailing_pe": "trailing P/E",
    "free_cash_flow_ttm": "free cash flow (TTM)",
    "free_cash_flow": "free cash flow",
    "enterprise_to_ebitda": "EV/EBITDA",
    "liabilities_to_equity": "liabilities/equity",
    "net_margin_ttm": "net margin (TTM)",
    "net_margin": "net margin",
    "market_cap": "market cap",
    "enterprise_value": "enterprise value",
    "total_debt": "total debt",
    "revenue": "revenue",
}

_PERCENT_METRICS = {
    "revenue_growth_yoy", "revenue_growth", "fcf_margin", "operating_margin_ttm",
    "operating_margin", "net_margin_ttm", "net_margin",
}
_MULTIPLE_METRICS = {"trailing_pe", "enterprise_to_ebitda", "liabilities_to_equity", "price_to_sales_ttm"}


def metric_label(metric: str) -> str:
    return _METRIC_LABELS.get(metric, metric.replace("_", " "))


def format_value(value: float | int | str | None, unit: str | None, metric: str) -> str:
    if value is None:
        return "no data"
    if unit == "USD" and isinstance(value, (int, float)):
        magnitude = abs(value)
        if magnitude >= 1e9:
            return f"${value / 1e9:.1f}B"
        if magnitude >= 1e6:
            return f"${value / 1e6:.1f}M"
        return f"${value:,.0f}"
    if unit == "ratio" and isinstance(value, (int, float)):
        if metric in _PERCENT_METRICS:
            return f"{value * 100:.1f}%"
        if metric in _MULTIPLE_METRICS:
            return f"{value:.2f}x"
        return f"{value:.3f}"
    if unit == "USD/shares" and isinstance(value, (int, float)):
        return f"${value:.2f}"
    if unit == "employees" and isinstance(value, (int, float)):
        return f"{int(value):,} employees"
    return str(value)

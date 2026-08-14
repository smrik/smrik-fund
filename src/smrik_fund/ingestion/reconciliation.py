"""Deterministic source reconciliation for reported P&L subtotals."""

from pathlib import Path

import pandas as pd

from .statements import ANNUAL_PERIOD_PATTERN


def _value(pnl, period, name, concept=None):
    column = "standard_concept" if concept else "label"
    target = concept or name
    matches = pnl.index[pnl[column].eq(target).fillna(False)]
    if len(matches) != 1:
        return None

    try:
        value = float(pnl.loc[matches[0], period])
    except (TypeError, ValueError):
        return None
    return None if pd.isna(value) else value


def _add_check(
    checks,
    *,
    check_id,
    period,
    subtotal,
    expression,
    values,
    reported_value,
    calculated_value,
    tolerance,
):
    missing = [name for name, value in values.items() if value is None]
    if reported_value is None:
        missing.append(subtotal)
    if calculated_value is None and not missing:
        missing.append("calculated subtotal")

    if missing:
        difference = None
        status = "SKIPPED"
        message = f"SKIPPED: {expression}; missing {', '.join(missing)}"
        output_calculated_value = None
    else:
        difference = calculated_value - reported_value
        status = "PASS" if abs(difference) <= tolerance else "FAIL"
        message = f"{status}: {expression}; difference={difference:g}"
        output_calculated_value = calculated_value

    checks.append(
        {
            "check_id": check_id,
            "period": period,
            "subtotal": subtotal,
            "reported_value": reported_value,
            "calculated_value": output_calculated_value,
            "difference": difference,
            "status": status,
            "acknowledged": False,
            "affected_lines": "; ".join([*values, subtotal]),
            "message": message,
        }
    )


def reconcile_pnl(
    pnl: pd.DataFrame,
    tolerance: float = 1e-6,
) -> pd.DataFrame:
    """Reconcile the four safe reported P&L subtotal relationships."""
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")

    periods = [
        column
        for column in pnl.columns
        if isinstance(column, str) and ANNUAL_PERIOD_PATTERN.fullmatch(column)
    ]
    if not periods:
        raise ValueError("analytical P&L must contain annual FY periods")

    checks = []
    for period in periods:
        # Revenue - Cost of revenue = Gross profit.
        revenue = _value(pnl, period, "Revenue", concept="Revenue")
        cost_of_revenue = _value(
            pnl,
            period,
            "Cost of revenue",
            concept="CostOfGoodsAndServicesSold",
        )
        gross_profit = _value(
            pnl,
            period,
            "Gross profit",
            concept="GrossProfit",
        )
        gross_profit_calculated = (
            revenue - cost_of_revenue
            if revenue is not None and cost_of_revenue is not None
            else None
        )
        _add_check(
            checks,
            check_id="gross_profit",
            period=period,
            subtotal="Gross profit",
            expression="Revenue - Cost of revenue = Gross profit",
            values={"Revenue": revenue, "Cost of revenue": cost_of_revenue},
            reported_value=gross_profit,
            calculated_value=gross_profit_calculated,
            tolerance=tolerance,
        )

        # Gross profit - operating expenses = Operating income.
        research_and_development = _value(
            pnl,
            period,
            "Research and development",
            concept="ResearchAndDevelopmentExpenses",
        )
        sales_and_marketing = _value(pnl, period, "Sales and marketing")
        general_and_administrative = _value(
            pnl,
            period,
            "General and administrative",
        )
        operating_income = _value(
            pnl,
            period,
            "Operating income",
            concept="OperatingIncomeLoss",
        )
        if (
            gross_profit is None
            or research_and_development is None
            or sales_and_marketing is None
            or general_and_administrative is None
        ):
            operating_income_calculated = None
        else:
            operating_income_calculated = (
                gross_profit
                - research_and_development
                - sales_and_marketing
                - general_and_administrative
            )
        _add_check(
            checks,
            check_id="operating_income",
            period=period,
            subtotal="Operating income",
            expression=(
                "Gross profit - Research and development - Sales and marketing "
                "- General and administrative = Operating income"
            ),
            values={
                "Gross profit": gross_profit,
                "Research and development": research_and_development,
                "Sales and marketing": sales_and_marketing,
                "General and administrative": general_and_administrative,
            },
            reported_value=operating_income,
            calculated_value=operating_income_calculated,
            tolerance=tolerance,
        )

        # Operating income + other income/expense = Pretax income.
        other_income = _value(
            pnl,
            period,
            "Other income (expense), net",
            concept="NonoperatingIncomeExpense",
        )
        pretax_income = _value(
            pnl,
            period,
            "Income before income taxes",
            concept="PretaxIncomeLoss",
        )
        pretax_income_calculated = (
            operating_income + other_income
            if operating_income is not None and other_income is not None
            else None
        )
        _add_check(
            checks,
            check_id="pretax_income",
            period=period,
            subtotal="Income before income taxes",
            expression=(
                "Operating income + Other income (expense), net "
                "= Income before income taxes"
            ),
            values={
                "Operating income": operating_income,
                "Other income (expense), net": other_income,
            },
            reported_value=pretax_income,
            calculated_value=pretax_income_calculated,
            tolerance=tolerance,
        )

        # Pretax income - income taxes = Net income.
        income_taxes = _value(
            pnl,
            period,
            "Provision for income taxes",
            concept="IncomeTaxes",
        )
        net_income = _value(pnl, period, "Net income", concept="NetIncome")
        net_income_calculated = (
            pretax_income - income_taxes
            if pretax_income is not None and income_taxes is not None
            else None
        )
        _add_check(
            checks,
            check_id="net_income",
            period=period,
            subtotal="Net income",
            expression=(
                "Income before income taxes - Provision for income taxes "
                "= Net income"
            ),
            values={
                "Income before income taxes": pretax_income,
                "Provision for income taxes": income_taxes,
            },
            reported_value=net_income,
            calculated_value=net_income_calculated,
            tolerance=tolerance,
        )

    return pd.DataFrame(checks)


def save_reconciliation_checks(
    ticker: str,
    checks: pd.DataFrame,
    output_root: str | Path = "data",
) -> Path:
    """Save reconciliation checks under the canonical output stage."""
    output_path = (
        Path(output_root)
        / ticker.strip().upper()
        / "03_output"
        / "reconciliation_checks.csv"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    checks.to_csv(output_path, index=False)
    return output_path

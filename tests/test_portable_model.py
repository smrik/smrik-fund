import copy
import json
from pathlib import Path

import pandas as pd
import pytest
from test_company_case import filing

from smrik_fund.company_case import freeze_filings, validate_case
from smrik_fund.company_run import build, completed_analyst
from smrik_fund.portable_model import flow_column, flow_windows, prepare_model

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("ticker,end,cash", [("LULU", "2027-01-31", 1389.737), ("BBWI", "2027-01-30", 794)])
def test_retail_fiscal_dates_and_reported_claims(ticker, end, cash, tmp_path):
    model = prepare_model(ROOT / f"data/weekend/20260919/{ticker}/base-r1/source")
    assert model["periods"][0] == {"id": "FY2026_STUB", "end": end, "fraction": 0.5, "elapsed": 182/365}
    opening = model["opening"]
    assert opening["cash"] == cash
    assert opening["assets"] - opening["liabilities"] == pytest.approx(opening["equity"])
    assert any(a["group"] == "quarterly share period" for a in model["allocations"])
    snapshot = build(model, tmp_path / ticker)
    assert snapshot["mechanical"] == snapshot["valuation_gate"] == "PASS"
    expected = snapshot["enterprise_value"] + cash + opening["short_investments"] + opening["long_investments"] - opening["current_debt"] - opening["long_debt"] - opening.get("minority_interest_proxy", 0)
    assert snapshot["equity_value"] == pytest.approx(expected)
    if ticker == "BBWI":
        assert opening["minority_interest_proxy"] == 2
        assert opening["liabilities"] == 6210
        assert opening["equity"] == -1054
    else:
        assert any("reported balance-sheet caption" in e["concept"] for e in model["evidence"])


@pytest.mark.parametrize("change", ["caption", "amount", "restriction"])
def test_cash_caption_classification_rejects_conflicting_source(monkeypatch, change):
    from smrik_fund.company_notes import note_claims

    case = ROOT / "data/weekend/20260919/LULU/base-r1/source"
    meta = json.loads((case / "0001397187-26-000127/filing.json").read_text())
    original = Path.read_text
    if change == "restriction":
        monkeypatch.setattr(Path, "read_text", lambda path, *a, **kw: original(path, *a, **kw) + "\nRestricted cash requires separate treatment.")
    with pytest.raises(ValueError, match="Combined cash"):
        note_claims(case, meta, [], cash_total=1389.737 if change != "amount" else 1390, cash_caption="Cash and cash equivalents" if change != "caption" else "Cash and restricted cash")


def test_minority_claim_must_reconcile(monkeypatch):
    original = pd.read_csv

    def altered(path, *args, **kwargs):
        df = original(path, *args, **kwargs)
        if Path(path).name == "balance_sheet.csv":
            df.loc[df.concept.eq("us-gaap_MinorityInterest"), "2026-08-01"] = 3e6
        return df

    monkeypatch.setattr(pd, "read_csv", altered)
    with pytest.raises(ValueError, match="minority interest do not reconcile"):
        prepare_model(ROOT / "data/weekend/20260919/BBWI/base-r1/source")


def test_hpq_combined_cash_requires_explicit_note_reconciliation(tmp_path):
    case = ROOT / "data/daily/20260916-hpq-deep/source"
    model = prepare_model(case)
    assert model["opening"]["cash"] == 4169
    assert any(e["concept"] == "RestrictedCashAndCashEquivalentsAtCarryingValue" and e["reported_value"] == 0 for e in model["evidence"])
    snapshot = build(model, tmp_path / "hpq")
    assert snapshot["mechanical"] == snapshot["valuation_gate"] == "PASS"


@pytest.mark.parametrize("change", ["nonzero", "missing", "duplicate", "wrong_currency"])
def test_combined_cash_note_rejects_unproven_available_cash(monkeypatch, change):
    from smrik_fund.company_notes import note_claims

    case = ROOT / "data/daily/20260916-hpq-deep/source"
    meta = json.loads((case / "0000047217-26-000051/filing.json").read_text())
    original = pd.read_csv

    def altered(path, *args, **kwargs):
        df = original(path, *args, **kwargs)
        mask = df.concept.eq("us-gaap:RestrictedCashAndCashEquivalentsAtCarryingValue") & df.period_instant.eq(meta["measurement_date"])
        if change == "nonzero":
            df.loc[mask, "numeric_value"] = 1e6
        elif change == "missing":
            df = df.loc[~mask]
        elif change == "duplicate":
            df = pd.concat([df, df.loc[mask]], ignore_index=True)
        else:
            df.loc[mask, "currency"] = "EUR"
        return df

    monkeypatch.setattr(pd, "read_csv", altered)
    with pytest.raises(ValueError, match="Combined cash|Ambiguous"):
        note_claims(case, meta, [], cash_total=4169)

CASES = {
    "NVDA": ROOT / "data/multi-ticker/20260910/NVDA/attempt-r2/source",
    "COST": ROOT / "data/multi-ticker/20260910/COST/attempt-r2/source",
    "GOOGL": ROOT / "data/multi-ticker/portable/GOOGL/source",
    "AMZN": ROOT / "data/multi-ticker/portable/AMZN/source-with-notes",
}


def test_cik_alias_and_cross_company_rejection(tmp_path):
    freeze_filings("OTHERCLASS", "2025-10-31", [filing()], tmp_path / "alias", expected_cik="320193")
    assert validate_case(tmp_path / "alias")["ticker"] == "OTHERCLASS"
    with pytest.raises(ValueError, match="ticker"):
        freeze_filings("AAPL", "2025-10-31", [filing()], tmp_path / "wrong", expected_cik="1652044")
    assert not (tmp_path / "wrong").exists()


def test_costco_exact_36_week_windows_and_ambiguity():
    sources = [json.loads(p.read_text()) for p in CASES["COST"].glob("*/filing.json")]
    annual = next(s for s in sources if s["form"] == "10-K")
    quarter = next(s for s in sources if s["form"] == "10-Q")
    _, current, prior = flow_windows(annual, quarter)
    assert (current["start_date"], current["end_date"]) == ("2025-09-01", "2026-05-10")
    assert (prior["start_date"], prior["end_date"]) == ("2024-09-02", "2025-05-11")
    altered = copy.deepcopy(quarter)
    altered["reporting_periods"].append(current)
    with pytest.raises(ValueError, match="ambiguous"):
        flow_windows(annual, altered)


def test_first_quarter_flow_column_and_annual_only():
    p = {"start_date": "2026-01-01", "end_date": "2026-03-31", "days": 89}
    assert flow_column(pd.DataFrame(columns=["2026-03-31 (Q1)"]), p) == "2026-03-31 (Q1)"
    annual = next(json.loads(p.read_text()) for p in CASES["COST"].glob("*/filing.json") if json.loads(p.read_text())["form"] == "10-K")
    _, current, prior = flow_windows(annual, annual)
    assert current is prior is None


@pytest.mark.parametrize("ticker", CASES)
def test_real_company_accounting_and_beta_independence(ticker, tmp_path):
    model = prepare_model(CASES[ticker])
    o = model["opening"]
    assert o["assets"] - o["liabilities"] == pytest.approx(o["equity"])
    assert model["history"]["capex_cash"]["ttm"] < 0
    snapshot = build(model, tmp_path / "base")
    assert len(snapshot["schedules"]) == 52
    assert snapshot["mechanical"] == snapshot["valuation_gate"] == "PASS"
    rows = snapshot["schedules"]
    assert max(abs(x) for x in rows["Balance difference (no cash/equity plug)"]) < 1e-6
    # Independent economic cash-flow bridge, including financing and SBC.
    tax = model["history"]["tax"]["ttm"] / model["history"]["pretax"]["ttm"]
    for i in range(11):
        bridge = rows["Economic UFCF (SBC remains expensed)"][i] + rows["SBC cash-flow addback / equity contribution"][i] + (rows["Investment income (scenario risk-free yield)"][i] - rows["Interest expense on constant refinanced debt"][i]) * (1-tax)
        assert rows["Cash FCF"][i] == pytest.approx(bridge, abs=1e-6)
    changed = copy.deepcopy(model)
    changed["controls"]["beta"] += 0.1
    revised = build(changed, tmp_path / "revision")
    assert revised["schedules"] == rows
    assert revised["per_share_value"] < snapshot["per_share_value"]


@pytest.mark.parametrize("change", ["missing", "duplicate", "null", "financial"])
def test_bad_required_source_or_financial_institution_is_blocked(monkeypatch, change):
    original = pd.read_csv

    def altered(path, *args, **kwargs):
        df = original(path, *args, **kwargs)
        if Path(path).name == "balance_sheet.csv":
            match = df.concept.eq("us-gaap_AssetsCurrent")
            if change == "missing":
                df = df.loc[~match]
            elif change == "duplicate":
                df = pd.concat([df, df.loc[match]])
            elif change == "null":
                df.loc[match, "2026-05-10"] = None
            else:
                df.loc[match, "concept"] = "us-gaap_Deposits"
        return df

    monkeypatch.setattr(pd, "read_csv", altered)
    with pytest.raises(ValueError, match="Unsupported|Missing/ambiguous"):
        prepare_model(CASES["COST"])


def test_amazon_signed_tax_and_hierarchy_are_preserved():
    m = prepare_model(CASES["AMZN"])
    assert m["history"]["tax_reported"]["ttm"] < 0
    assert m["history"]["tax"]["ttm"] > 0
    for period in ("annual", "current_ytd", "prior_ytd", "ttm"):
        f = m["history"]
        assert f["pretax"][period] + f["tax_reported"][period] + f["equity_income_after_tax"][period] == pytest.approx(f["net_income"][period])
    assert any(a["group"] == "total liabilities" and "direct liability children" in a["basis"] for a in m["allocations"])
    assert m["opening"]["long_investments"] == 224895
    assert m["opening"]["current_debt"] == 1688
    assert any(a["group"] == "finance lease debt claim" and a["value"] == 13451 for a in m["allocations"])


def test_ambiguous_note_claim_is_not_summed(monkeypatch):
    original = pd.read_csv

    def duplicate(path, *args, **kwargs):
        df = original(path, *args, **kwargs)
        if Path(path).name == "note_facts.csv":
            df = pd.concat([df, df.loc[df.concept.eq("us-gaap:FinanceLeaseLiabilityCurrent")]])
        return df

    monkeypatch.setattr(pd, "read_csv", duplicate)
    with pytest.raises(ValueError, match="Ambiguous/unit-incompatible note"):
        prepare_model(CASES["AMZN"])


def test_annual_only_full_forecast_has_no_invented_ytd(monkeypatch):
    from smrik_fund import portable_model

    manifest = validate_case(CASES["NVDA"])
    manifest["selected_filings"] = [a for a in manifest["selected_filings"] if json.loads((CASES["NVDA"] / a / "filing.json").read_text())["form"] == "10-K"]
    monkeypatch.setattr(portable_model, "validate_case", lambda _: manifest)
    m = prepare_model(CASES["NVDA"])
    assert m["periods"][0]["id"] == "FY2027"
    assert m["periods"][0]["fraction"] == 1
    assert m["history"]["revenue"]["ttm"] == m["history"]["revenue"]["annual"]


def test_completed_analyst_reuse_is_bound_to_case_and_response(tmp_path):
    source = ROOT / "data/multi-ticker/portable/AMZN/live-r2"
    for name in ("analyst.request.json", "analyst.response.json", "analyst.receipt.json"):
        (tmp_path / name).write_bytes((source / name).read_bytes())
    request = json.loads((tmp_path / "analyst.request.json").read_text())
    case_hash = json.loads(request["input"])["model"]["case_hash"]
    assert completed_analyst(tmp_path, case_hash)["controls"]["payout_ratio"] == 0
    with pytest.raises(ValueError, match="different source case"):
        completed_analyst(tmp_path, "different")
    (tmp_path / "analyst.response.json").write_text("{}")
    with pytest.raises(ValueError, match="binding changed"):
        completed_analyst(tmp_path, case_hash)

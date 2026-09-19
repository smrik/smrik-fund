"""Strict, source-bound note detail for claims embedded in face aggregates."""

import math
import re

import pandas as pd


def note_claims(case_dir, metadata, evidence, *, cash_total=None, cash_caption=None):
    root = case_dir / metadata["accession"]
    path = root / "note_facts.csv"
    if not path.exists():
        return None
    facts = pd.read_csv(path, low_memory=False)
    current = facts.loc[facts.period_instant.eq(metadata["measurement_date"])]

    def amount(concept, member=None):
        rows = current.loc[current.concept.eq("us-gaap:" + concept)]
        if member is None:
            rows = rows.loc[~rows.is_dimensioned.astype(str).str.lower().eq("true")]
        else:
            rows = rows.loc[rows.member.eq(member)]
            dims = [c for c in rows if c.startswith("dim_") and c not in {"dim_us-gaap_DerivativeInstrumentRiskAxis", "dim_us-gaap_FairValueByFairValueHierarchyLevelAxis"}]
            rows = rows.loc[~rows[dims].notna().any(axis=1)]
        if rows.empty:
            return None
        if len(rows) != 1 or rows.iloc[0].currency != "USD" or str(int(rows.iloc[0].entity_identifier)) != str(int(metadata["cik"])):
            raise ValueError(f"Ambiguous/unit-incompatible note fact: {concept}")
        value = float(rows.iloc[0].numeric_value)
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"Missing/invalid note fact: {concept}")
        evidence.append({"id": f"S{len(evidence)+1}", "file": f"{metadata['accession']}/note_facts.csv", "line": int(rows.index[0])+2, "concept": concept, "column": metadata["measurement_date"], "reported_value": value, "display_value": value/1e6, "units": "USD millions", "context_ref": rows.iloc[0].context_ref, "dimension_member": member})
        return value/1e6

    if cash_total is not None:
        cash = amount("CashAndCashEquivalentsAtCarryingValue")
        restricted = amount("RestrictedCashAndCashEquivalentsAtCarryingValue")
        if cash is None and restricted is None and cash_caption == "Cash and cash equivalents":
            text = (root / "source.txt").read_text()
            # A broad tag is not automatically a combined-cash classification. Bind
            # the narrower face caption to the original balance sheet and units.
            section = re.search(r"CONSOLIDATED BALANCE SHEETS(.{0,5000})", text, re.S)
            line = re.search(r"^\s*Cash and cash equivalents\s+\$\s*([\d,]+)(?=\s)", section[1], re.M) if section else None
            if (line and "Amounts in thousands" in section[1]
                    and abs(float(line[1].replace(",", ""))/1000-cash_total) < 0.001
                    and not re.search(r"restricted cash", text, re.I)
                    and amount("CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents") == cash_total):
                evidence.append({"id": f"S{len(evidence)+1}", "file": f"{metadata['accession']}/source.txt", "line": text[:section.start(1)+line.start()].count("\n")+1, "concept": "Cash classification from reported balance-sheet caption", "column": metadata["measurement_date"], "display_value": cash_total, "units": "USD millions", "excerpt": line[0].strip()})
                return {"unrestricted_cash": cash_total, "basis": "Reported cash-and-cash-equivalents caption and amount matched to original balance sheet in thousands and native fact; broad tag preserved. No restricted-cash fact or text disclosure; classification estimate, not an invented zero restricted balance."}
        if cash is None or restricted != 0 or abs(cash - cash_total) > 0.001:
            raise ValueError("Combined cash needs a reconciled note with explicitly zero restricted cash; nonzero restrictions require a separate forecast policy")
        return {"unrestricted_cash": cash, "basis": "Combined face cash reconciles to note cash and explicitly reported zero restricted cash; no restriction assumed away"}

    finance_current = amount("FinanceLeaseLiabilityCurrent")
    finance_long = amount("FinanceLeaseLiabilityNoncurrent")
    if (finance_current is None) != (finance_long is None):
        raise ValueError("Incomplete current/noncurrent finance-lease split")
    if finance_current is not None:
        total = amount("FinanceLeaseLiability")
        if total is not None and abs(finance_current + finance_long - total) > 0.001:
            raise ValueError("Finance-lease note components do not reconcile")
    text = (root / "source.txt").read_text()
    investments = None
    # Location assertion is required before removing these assets from Other assets.
    location = re.search(r"These non-marketable investments are included within.{0,100}Other assets", text, re.I)
    if location:
        components = [amount("EquitySecuritiesWithoutReadilyDeterminableFairValueAmount"), amount("EquityMethodInvestments"), amount("DerivativeAssets", "us-gaap:WarrantMember")]
        convertible = amount("AvailableForSaleSecuritiesDebtSecurities")
        if convertible is not None:
            excerpt = re.search(r"convertible notes recorded on our consolidated balance sheets was approximately.{0,220}", text, re.I)
            if excerpt is None or not re.search(rf"\$\s*{re.escape(f'{convertible/1000:g}')}\s*billion", excerpt[0]):
                raise ValueError("Convertible investment fact lacks an exact nonmarketable note-text binding")
            components.append(convertible)
        if any(v is None for v in components):
            raise ValueError("Incomplete supported nonmarketable investment note detail")
        investments = sum(components)
        evidence.append({"id": f"S{len(evidence)+1}", "file": f"{metadata['accession']}/source.txt", "line": text[:location.start()].count("\n")+1, "concept": "Nonmarketable investment location", "column": metadata["measurement_date"], "display_value": investments, "units": "USD millions", "excerpt": location[0]})
    return {"finance_current": finance_current, "finance_noncurrent": finance_long, "nonmarketable_investments": investments}

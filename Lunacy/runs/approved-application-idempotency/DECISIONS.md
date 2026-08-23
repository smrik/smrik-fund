# Decisions

## D1 — materiality boundary

User authorized a frozen explicit `materiality_passed=True` fact for the deterministic lifecycle proof. This fact may be supplied at the frozen test/integration boundary only. Do not implement a numeric materiality threshold or change live MSFT materiality policy; live unknown materiality remains fail-closed/human-review.

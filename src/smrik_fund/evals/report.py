"""Human-readable summaries and baseline comparison.

JSON stays authoritative; Markdown is for people and coding agents.  Comparison
reports deltas only - it never decides whether a change should be kept.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ORDINAL = {"FAIL": 0, "PARTIAL": 1, "PASS": 2}


def summarize(iteration: dict[str, Any]) -> str:
	"""Render one iteration as a compact Markdown report."""
	lines = [
		f"# Evaluation iteration {iteration['iteration_id']}",
		"",
		f"- Definition: `{iteration['definition_hash'][:16]}`",
		f"- Judge: {iteration['judge']['model']} "
		f"({iteration['judge']['reasoning_effort']})",
		f"- Calls: product {iteration['calls']['product']}, "
		f"judge {iteration['calls']['judge']}",
		f"- Preflight: {iteration['preflight']['status']}",
		f"- HEAD: `{(iteration['repository'].get('head_sha') or 'unknown')[:12]}`"
		f" dirty={iteration['repository']['dirty']}",
		"",
		"| Case | Case status | Product | Valid | Judge | Verdict |",
		"|---|---|---|---|---|---|",
	]
	for case in iteration["cases"]:
		lines.append(
			f"| {case['case_id']} | {case['case_status']} | "
			f"{case['product_status']} | {case.get('product_valid')} | "
			f"{case['judge_status']} | {case.get('qualitative_verdict') or '-'} |"
		)

	vacuous = [
		(case["case_id"], c)
		for case in iteration["cases"]
		for c in case.get("checks", [])
		if c.get("status") == "NOT_APPLICABLE"
	]
	if vacuous:
		lines += [
			"",
			"## Checks with nothing to examine",
			"",
			"These did not pass; they had no content to assess.",
			"",
		]
		for case_id, entry in vacuous:
			lines.append(
				f"- `{case_id}` / **{entry['id']}**: {entry.get('reason', '')}"
			)

	failures = [
		(case["case_id"], c)
		for case in iteration["cases"]
		for c in case.get("checks", [])
		if c.get("status") == "FAIL"
	]
	if failures:
		lines += ["", "## Failing checks", ""]
		for case_id, entry in failures:
			marker = "critical" if entry.get("critical") else "diagnostic"
			lines.append(
				f"- `{case_id}` / **{entry['id']}** ({marker}): "
				f"{entry.get('reason', 'see case.json')}"
			)

	judged = [c for c in iteration["cases"] if c.get("judge")]
	if judged:
		lines += ["", "## Qualitative dimensions", ""]
		for case in judged:
			lines.append(f"### {case['case_id']} — {case['qualitative_verdict']}")
			for dimension in case["judge"]["dimensions"]:
				lines.append(
					f"- **{dimension['dimension']}**: {dimension['verdict']} — "
					f"{dimension['reason']}"
				)
			lines.append("")
	return "\n".join(lines).rstrip() + "\n"


def _load(value: str | Path | dict[str, Any]) -> dict[str, Any]:
	if isinstance(value, dict):
		return value
	path = Path(value)
	if path.is_dir():
		path = path / "iteration.json"
	return json.loads(path.read_text(encoding="utf-8"))


def _direction(current: str | None, baseline: str | None) -> str:
	if current is None or baseline is None:
		return "unavailable"
	if current == baseline:
		return "unchanged"
	left, right = _ORDINAL.get(current), _ORDINAL.get(baseline)
	if left is None or right is None:
		return "changed"
	return "improved" if left > right else "regressed"


def compare(
	current: str | Path | dict[str, Any], baseline: str | Path | dict[str, Any]
) -> dict[str, Any]:
	"""Report per-case and per-dimension deltas against a chosen baseline."""
	now, base = _load(current), _load(baseline)
	if now["definition_hash"] != base["definition_hash"]:
		return {
			"status": "NON_COMPARABLE",
			"reason": "evaluation definition differs from the selected baseline",
			"current_definition_hash": now["definition_hash"],
			"baseline_definition_hash": base["definition_hash"],
		}

	base_cases = {case["case_id"]: case for case in base["cases"]}
	deltas: list[dict[str, Any]] = []
	for case in now["cases"]:
		prior = base_cases.get(case["case_id"])
		if prior is None:
			deltas.append({"case_id": case["case_id"], "status": "NEW"})
			continue
		dimensions = []
		current_dims = {
			d["dimension"]: d["verdict"]
			for d in (case.get("judge") or {}).get("dimensions", [])
		}
		baseline_dims = {
			d["dimension"]: d["verdict"]
			for d in (prior.get("judge") or {}).get("dimensions", [])
		}
		for name in sorted(set(current_dims) | set(baseline_dims)):
			left, right = current_dims.get(name), baseline_dims.get(name)
			dimensions.append(
				{
					"dimension": name,
					"baseline": right,
					"current": left,
					"direction": _direction(left, right),
				}
			)
		deltas.append(
			{
				"case_id": case["case_id"],
				"product_status": {
					"baseline": prior.get("product_status"),
					"current": case.get("product_status"),
				},
				"product_valid": {
					"baseline": prior.get("product_valid"),
					"current": case.get("product_valid"),
				},
				"overall": {
					"baseline": prior.get("qualitative_verdict"),
					"current": case.get("qualitative_verdict"),
					"direction": _direction(
						case.get("qualitative_verdict"),
						prior.get("qualitative_verdict"),
					),
				},
				"dimensions": dimensions,
			}
		)
	return {
		"status": "COMPARABLE",
		"definition_hash": now["definition_hash"],
		"current_iteration": now["iteration_id"],
		"baseline_iteration": base["iteration_id"],
		"cases": deltas,
		"note": "Deltas only. KEEP/REVERT is a human or repair-agent decision.",
	}


def write_reports(iteration: dict[str, Any], run_dir: str | Path) -> Path:
	"""Write the Markdown summary next to the authoritative JSON."""
	path = Path(run_dir) / "summary.md"
	path.write_text(summarize(iteration), encoding="utf-8")
	return path


def update_ledger(output_root: str | Path) -> Path:
	"""Rebuild the compact Markdown index over the iteration ledger."""
	root = Path(output_root)
	records = sorted((root / "iterations").glob("*.json"))
	lines = ["# Evaluation iterations", "", "| Iteration | Definition | Cases | Product calls | Judge calls |", "|---|---|---|---|---|"]
	for record in records:
		data = json.loads(record.read_text(encoding="utf-8"))
		lines.append(
			f"| `{data['iteration_id']}` | `{data['definition_hash'][:12]}` | "
			f"{len(data['cases'])} | {data['calls']['product']} | "
			f"{data['calls']['judge']} |"
		)
	path = root / "iterations.md"
	path.write_text("\n".join(lines) + "\n", encoding="utf-8")
	return path

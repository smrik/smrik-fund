"""Read-only research audit: evidence integrity is separate from financial approval.

Run folders are the database. This module reads existing artifacts, verifies their
bindings, and explains what passed or stopped. It never fetches data or runs an LLM.
"""

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from smrik_fund.analysis_budget import content_hash
from smrik_fund.company_case import validate_case
from smrik_fund.daily_research import build_report

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"
RUN_AREAS = (
	"daily",
	"weekend",
	"multi-ticker",
	"second-company",
	"coverage",
	"workspace",
)


def read_json(path: Path) -> dict:
	return json.loads(path.read_text(encoding="utf-8-sig"))


def file_hash(path: Path) -> str:
	return hashlib.sha256(path.read_bytes()).hexdigest()


def within_data(path: Path, data_root: Path) -> Path:
	"""Resolve junctions/symlinks before exposing any local research artifact."""
	path = path.resolve()
	if not path.is_relative_to(data_root.resolve()):
		raise ValueError("Research path leaves the local data directory")
	return path


def verify_screen(run_dir: Path, data_root: Path | None = None) -> dict:
	"""Recompute screening decisions from frozen inputs at the original run time."""
	if data_root is not None:
		for name in ("report.json", "snapshot.json"):
			within_data(run_dir / name, data_root)
	report = read_json(run_dir / "report.json")
	snapshot = read_json(run_dir / "snapshot.json")
	if content_hash(snapshot) != report["snapshot_hash"]:
		raise ValueError("Screen report/raw snapshot binding changed")
	expected = build_report(
		snapshot,
		shortlist_size=report["shortlist_limit"],
		now=datetime.fromisoformat(report["created_at"]),
	)
	for key in ("shortlist", "counts", "filters", "scope", "status"):
		if report[key] != expected[key]:
			raise ValueError(f"Screen {key} differs from frozen evidence")

	# Attached DCF summaries are not inputs to screening. Check every actual
	# screening field, including method/issuer routing, before a deep run.
	def rows(value):
		return [{k: v for k, v in row.items() if k != "model"} for row in value["rows"]]

	if rows(report) != rows(expected):
		raise ValueError("Screen company evidence differs from frozen inputs")
	return report


def list_runs(data_root: Path = DATA_ROOT) -> list[dict]:
	"""Index recognized run folders, pruning raw filings and browser caches."""
	runs = []
	for area in RUN_AREAS:
		for directory, children, files in os.walk(data_root / area):
			children[:] = [
				c
				for c in children
				if c
				not in {
					"source",
					"reviewed",
					"cache",
					"market",
					"browser-profile",
					"node_modules",
					"jobs",
				}
				and not c.startswith("candidate-")
			]
			root = Path(directory)
			marker = next(
				(
					n
					for n in (
						"report.json",
						"version.json",
						"blocked.json",
						"deep-result.json",
						"deep-inputs.json",
					)
					if n in files
				),
				None,
			)
			if marker is None:
				continue
			try:
				within_data(root, data_root)
				data = read_json(within_data(root / marker, data_root))
				kind = "screen" if marker == "report.json" else "company"
				runs.append(
					{
						"id": root.relative_to(data_root).as_posix(),
						"kind": kind,
						"ticker": data.get("ticker", "US screen"),
						"status": data.get("status", "INCOMPLETE"),
						"updated": (root / marker).stat().st_mtime,
						"counts": data.get("counts", {}),
						"reason": data.get("reason"),
					}
				)
			except (OSError, ValueError, KeyError, TypeError):
				runs.append(
					{
						"id": root.relative_to(data_root).as_posix(),
						"kind": "unknown",
						"ticker": "Unreadable run",
						"status": "INVALID_ARTIFACT",
						"updated": 0,
						"counts": {},
					}
				)
	return sorted(runs, key=lambda r: r["updated"], reverse=True)


def audit_run(run_dir: Path, data_root: Path = DATA_ROOT) -> dict:
	"""Inspect completion, financial caveats, and actual on-disk evidence bindings."""
	run_dir = within_data(run_dir, data_root)
	result = {
		"id": run_dir.relative_to(data_root.resolve()).as_posix(),
		"checks": [],
		"warnings": [],
		"artifacts": [],
		"events": [],
		"status": "INCOMPLETE",
		"assumptions": [],
		"sources": [],
	}

	def read(path):
		return read_json(within_data(path, data_root))

	def artifact(path, label):
		path = within_data(path, data_root)
		if path.is_file():
			result["artifacts"].append(
				{
					"label": label,
					"path": path.relative_to(data_root.resolve()).as_posix(),
				}
			)

	def check(label, operation):
		try:
			operation()
			result["checks"].append({"label": label, "status": "PASS"})
		except (OSError, ValueError, KeyError, TypeError) as exc:
			result["checks"].append(
				{"label": label, "status": "FAIL", "reason": str(exc)}
			)

	def require(condition, message):
		if not condition:
			raise ValueError(message)

	try:
		if (run_dir / "report.json").exists():
			report = read(run_dir / "report.json")
			result.update(
				kind="screen",
				status=report["status"],
				ticker="US screen",
				counts=report["counts"],
				created_at=report["created_at"],
				shortlist=report["shortlist"],
				companies=report["rows"],
				assumptions=report["assumptions"],
			)
			check(
				"Frozen market snapshot and reproduced screening decisions",
				lambda: verify_screen(run_dir, data_root),
			)
			result["warnings"].extend(report["issues"])
			for name, label in (
				("index.html", "Screen report"),
				("screen.csv", "All companies CSV"),
				("snapshot.json", "Frozen vendor inputs"),
				("report.json", "Screen calculations"),
			):
				artifact(run_dir / name, label)
		else:
			result["kind"] = "company"
			version = (
				read(run_dir / "version.json")
				if (run_dir / "version.json").exists()
				else None
			)
			outcome_path = run_dir / (
				"blocked.json"
				if (run_dir / "blocked.json").exists()
				else "deep-result.json"
			)
			outcome = read(outcome_path) if outcome_path.exists() else {}
			result.update(
				status=outcome.get(
					"status", (version or {}).get("status", "INCOMPLETE")
				),
				ticker=outcome.get(
					"ticker", (version or {}).get("ticker", run_dir.parent.name)
				),
			)
			if outcome.get("reason"):
				result["warnings"].append(outcome["reason"])
			model_file = run_dir / "reviewed/model.json"
			model = read(model_file) if model_file.exists() else {}
			if model:
				if not version:
					result["warnings"].append(
						"Unpublished candidate: final workbook verification did not complete."
					)
				result.update(
					assumptions=model["controls"],
					allocations=model.get("allocations", []),
					evidence=model.get("evidence", []),
					measurement_date=model["measurement_date"],
					information_cutoff=model["information_cutoff"],
					analyst=model.get("analyst", {}),
				)
				result["warnings"].extend(model.get("limitations", []))
				result["warnings"].append(
					"Passing mechanics is not financial approval. Reported TTM one-offs remain unless explicitly adjusted."
				)
			if version:
				for name, key in (
					("model.json", "model_sha256"),
					("snapshot.json", "snapshot_sha256"),
					(f"{version['ticker']}.xlsx", "workbook_sha256"),
				):
					path = within_data(run_dir / "reviewed" / name, data_root)
					check(
						f"Unchanged {name}",
						lambda p=path, k=key: require(
							file_hash(p) == version[k],
							"Artifact hash differs from published version",
						),
					)
					artifact(path, "Excel workbook" if name.endswith(".xlsx") else name)
				if model.get("workbook_template"):
					patch = model["workbook_template"]
					for name, key in (
						("template.xlsx", "sha256"),
						("template.json", "contract_sha256"),
					):
						path = within_data(run_dir / name, data_root)
						check(
							f"Unchanged {name}",
							lambda p=path, k=key: require(
								file_hash(p) == patch[k],
								"Frozen template differs from the calculated model",
							),
						)
						artifact(path, name)
				snapshot = read(run_dir / "reviewed/snapshot.json")
				check(
					"Accounting and valuation gates",
					lambda: require(
						snapshot["mechanical"] == snapshot["valuation_gate"] == "PASS",
						"Calculated gates did not pass",
					),
				)
				result["valuation"] = {
					k: snapshot[k]
					for k in (
						"per_share_value",
						"wacc",
						"enterprise_value",
						"equity_value",
					)
				}
				proof_file = run_dir / "native-excel-proof.json"
				if proof_file.exists():
					proof = read(proof_file)
					if version.get("native_excel_proof_sha256"):
						check(
							"Unchanged native Excel receipt",
							lambda: require(
								file_hash(proof_file)
								== version["native_excel_proof_sha256"],
								"Native Excel receipt differs from published version",
							),
						)
					else:
						result["warnings"].append(
							"Historical Excel receipt was not hash-bound in its version manifest."
						)
					check(
						"Native Excel recalculation and edit/restoration",
						lambda: require(
							proof["status"] == proof["native_beta_edit"] == "PASS"
							and abs(
								proof["per_share_value"] - snapshot["per_share_value"]
							)
							< 1e-6,
							"Native Excel proof failed or differs",
						),
					)
					result["native_excel"] = proof
				else:
					result["warnings"].append(
						"No native Excel validation receipt: formula-engine build only."
					)
			inputs = (
				read(run_dir / "deep-inputs.json")
				if (run_dir / "deep-inputs.json").exists()
				else {}
			)
			if inputs.get("ticker") and not outcome and not version:
				result["ticker"] = inputs["ticker"]
			if inputs.get("screen"):
				screen = within_data(Path(inputs["screen"]), data_root)

				def verify_selection():
					report = verify_screen(screen, data_root)
					require(
						file_hash(screen / "report.json") == inputs["report_sha256"]
						and report["snapshot_hash"] == inputs["snapshot_hash"],
						"Selected screen changed since the company run",
					)

				check(
					"Frozen screening selection for this company run", verify_selection
				)
			source = (
				model.get("case_dir")
				or inputs.get("source")
				or outcome.get("source")
				or str(run_dir / "source")
			)
			source = within_data(Path(source), data_root)
			if model and not (source / "case.json").exists():
				check(
					"Frozen SEC source manifest exists",
					lambda: require(
						False, "Source manifest missing; evidence cannot be verified"
					),
				)
			if (source / "case.json").exists():
				manifest = read(source / "case.json")
				check(
					"Frozen SEC source files, issuer and periods",
					lambda: validate_case(source),
				)
				if model:
					check(
						"Model bound to this source case",
						lambda: require(
							content_hash(manifest)
							== model["case_hash"]
							== (version or model)["case_hash"],
							"Source/model binding differs",
						),
					)
				for accession in manifest["selected_filings"]:
					filing = read(source / accession / "filing.json")
					result["sources"].append(
						{
							k: filing[k]
							for k in (
								"form",
								"filing_date",
								"measurement_date",
								"accession",
								"source_url",
							)
						}
					)
					for name in (
						"source.txt",
						"balance_sheet.csv",
						"income_statement.csv",
						"cash_flow_statement.csv",
						"note_facts.csv",
					):
						artifact(
							source / accession / name, f"{filing['form']} · {name}"
						)
				artifact(source / "case.json", "SEC source manifest")
			if model.get("research_packet_hash"):
				packet_path = run_dir / "research-packet.json"
				check(
					"Research packet bound to reviewed model",
					lambda: require(
						content_hash(read(packet_path))
						== model["research_packet_hash"],
						"Research packet differs from reviewed evidence",
					),
				)
				assessment_path = run_dir / "assessment-audit.json"
				if assessment_path.exists():
					assessment = read(assessment_path)
					for name, expected in assessment["artifacts"].items():
						path = within_data(run_dir / name, data_root)
						check(
							f"Assessment artifact {name}",
							lambda p=path, h=expected: require(
								file_hash(p) == h, "Assessment artifact changed"
							),
						)
				else:
					result["warnings"].append(
						"Model published, but IC synthesis/assessment audit did not complete."
					)
				ic_review_path = run_dir / "ic-review-audit.json"
				if ic_review_path.exists():
					for name, expected in read(ic_review_path)["artifacts"].items():
						path = within_data(run_dir / name, data_root)
						check(
							f"Independent IC artifact {name}",
							lambda p=path, h=expected: require(
								file_hash(p) == h,
								"Independently reviewed IC artifact changed",
							),
						)
			for name in (
				"version.json",
				"run.json",
				"deep-inputs.json",
				"operator-assumptions.json",
				"native-excel-proof.json",
				"blocked.json",
				"deep-result.json",
				"events.jsonl",
				"ASSESSMENT.md",
				"IC.md",
				"IC-reviewed.md",
				"ic-review-audit.json",
				"research-packet.json",
				"assessment-audit.json",
			):
				artifact(run_dir / name, name)
		if (run_dir / "events.jsonl").exists():
			result["events"] = [
				json.loads(line)
				for line in within_data(run_dir / "events.jsonl", data_root)
				.read_text()
				.splitlines()
				if line.strip()
			]
	except (OSError, ValueError, KeyError, TypeError) as exc:
		result["checks"].append(
			{
				"label": "Readable complete run artifacts",
				"status": "FAIL",
				"reason": str(exc),
			}
		)
	result["integrity"] = (
		"FAIL"
		if any(c["status"] == "FAIL" for c in result["checks"])
		else "PASS"
		if result["checks"]
		else "NOT_VERIFIED"
	)
	return result

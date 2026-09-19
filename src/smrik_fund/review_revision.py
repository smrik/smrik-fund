"""P11 review exports and explicit, bounded revisions of the MSFT valuation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from smrik_fund.analysis_budget import content_hash, reservation
from smrik_fund.analysis_transport import dispatch_request
from smrik_fund.analysis_workflow import (
	AREA_SEQUENCE,
	EvidenceRequest,
	IndependentRecheck,
	_strict_schema,
	retrieve_evidence,
	validate_review,
)

ROOT = Path(__file__).resolve().parents[2]
CURRENT = ROOT / "data/MSFT/current-review.json"
CURRENT_SCHEMA = "current-review-v1"
CONTROLS = {
	"beta": {"minimum": 0, "maximum": 3, "units": "unitless", "address": "Valuation!B14", "source": "MKT-BETA"},
	"terminal_growth": {"minimum": 0, "maximum": 0.05, "units": "decimal annual growth", "address": "Valuation!B27", "source": "AREA-PACKET:dcf_terminal"},
}
PROMPT_VERSION = "p11-known-valuation-revision-v1"


def read(path: Path) -> dict:
	return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path: Path) -> str:
	return hashlib.sha256(path.read_bytes()).hexdigest()


def read_snapshot(path: Path) -> dict:
	value = read(path)
	return value.get("snapshot", value)


def write_new(path: Path, value: dict) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	text = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
	if path.exists():
		if read(path) != value:
			raise ValueError(f"Existing artifact preserved; choose a new output directory: {path}")
		return
	with path.open("x", encoding="utf-8") as handle:
		handle.write(text)


@contextmanager
def _publication_lock():
	"""Serialize company publication without stale lock-file recovery rules."""
	lock_path = CURRENT.with_suffix(CURRENT.suffix + ".lock")
	lock_path.parent.mkdir(parents=True, exist_ok=True)
	with lock_path.open("a+b") as handle:
		# Windows denies reading a byte another publisher has locked.
		if os.fstat(handle.fileno()).st_size == 0:
			handle.write(b"0")
			handle.flush()
		handle.seek(0)
		if os.name == "nt":
			import msvcrt

			msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
		else:
			import fcntl

			fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
		try:
			yield
		finally:
			handle.seek(0)
			if os.name == "nt":
				msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
			else:
				fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _current_pointer() -> dict | None:
	if not CURRENT.exists():
		return None
	pointer = read(CURRENT)
	if pointer.get("schema_version") != CURRENT_SCHEMA or pointer.get("company") != "MSFT":
		raise ValueError("STALE_CONTEXT: current-review pointer schema or company is invalid")
	version_dir = Path(pointer["version_dir"])
	version_path = version_dir / "version.json"
	if not version_path.is_file() or digest(version_path) != pointer.get("version_sha256"):
		raise ValueError("STALE_CONTEXT: current-review pointer target changed")
	stored = read(version_path)
	if stored.get("version") != pointer.get("version"):
		raise ValueError("STALE_CONTEXT: current-review pointer version differs from its target")
	return pointer


def _atomic_current(pointer: dict) -> None:
	CURRENT.parent.mkdir(parents=True, exist_ok=True)
	file_descriptor, temporary_name = tempfile.mkstemp(
		prefix=f".{CURRENT.name}.", suffix=".tmp", dir=CURRENT.parent
	)
	temporary = Path(temporary_name)
	payload = json.dumps(pointer, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
	try:
		with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
			handle.write(payload)
			handle.flush()
			os.fsync(handle.fileno())
		os.replace(temporary, CURRENT)
	finally:
		if temporary.exists():
			temporary.unlink()


def _pointer_for(version: dict) -> dict:
	version_dir = Path(version["model_path"]).resolve().parent
	return {
		"schema_version": CURRENT_SCHEMA,
		"company": "MSFT",
		"version": version["version"],
		"version_dir": str(version_dir),
		"version_sha256": digest(version_dir / "version.json"),
	}


def _write_current(validated_version: dict) -> dict:
	"""Initialize an absent current pointer, or replay its exact existing target."""
	version_dir = Path(validated_version["model_path"]).resolve().parent
	validated = validate_version(version_dir)
	pointer = _pointer_for(validated)
	with _publication_lock():
		current = _current_pointer()
		if current is not None and current != pointer:
			raise ValueError("STALE_CONTEXT: a different authoritative version is already current")
		if current is None:
			_atomic_current(pointer)
	return pointer


def _require_current(version_dir: Path, version: str, version_sha256: str) -> dict:
	pointer = _current_pointer()
	if pointer is None:
		raise ValueError("STALE_CONTEXT: no authoritative current version is published")
	if (
		Path(pointer["version_dir"]).resolve() != version_dir.resolve()
		or pointer["version"] != version
		or pointer["version_sha256"] != version_sha256
	):
		raise ValueError("STALE_CONTEXT: expected prior version is no longer current")
	return pointer


def now() -> str:
	return datetime.now(UTC).isoformat()


def parse_instruction(text: str) -> dict:
	"""Only literal supported changes or an allowed-area research request."""
	match = re.fullmatch(r"\s*(?:set|change)\s+(beta|terminal[ _-]growth)\s+(?:to\s+)?([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(%)?\s*\.?\s*", text, re.IGNORECASE)
	if match:
		control = re.sub(r"[ -]", "_", match[1].lower())
		value = float(match[2])
		if match[3]:
			if control == "beta":
				raise ValueError("Beta is unitless; do not express it as a percentage")
			value /= 100
		return {"kind": "change", "control": control, "value": value}
	match = re.fullmatch(r"\s*(?:research|investigate)\s+([a-z_]+)\s*:\s*([^\r\n]{3,240})\s*", text, re.IGNORECASE)
	if match and match[1].lower() in AREA_SEQUENCE:
		return {"kind": "research", "area": match[1].lower(), "question": match[2].strip(), "status": "QUEUED_NOT_ADOPTED"}
	raise ValueError("Unsupported or ambiguous instruction. Use 'set beta to 1.15', 'set terminal growth to 3%', or 'research <financial_area>: <question>'.")


def _financial_values(snapshot: dict) -> dict:
	# Review labels/status may change on export; financial values and row identities may not.
	p9 = {key: value for key, value in snapshot["p9"].items() if key not in {"status", "formulas"}}
	return {"statements": {key: [{"row": row["row"], "values": row["values"]} for row in rows] for key, rows in snapshot["statements"].items()}, "p9": p9, "checks": snapshot["checks"], "all_period": snapshot["allPeriodStatus"]}


def _assert_mechanical(snapshot: dict) -> None:
	if snapshot["allPeriodStatus"] != "PASS" or any(value != "PASS" for value in snapshot["checks"]) or any(snapshot["p9"][key] != "PASS" for key in ("inputGate", "terminalGate", "claimCheck", "valuationGate")):
		raise ValueError("MECHANICAL_FAILURE: candidate did not pass; prior version preserved")


def _build(model_path: Path, workbook_path: Path, snapshot_path: Path) -> dict:
	if workbook_path.exists() or snapshot_path.exists():
		raise ValueError("Refusing to overwrite an exported or Excel-edited workbook")
	result = subprocess.run(["node", str(ROOT / "scripts/spreadsheet_compat/export-review.mjs"), str(model_path), str(workbook_path), str(snapshot_path)], cwd=ROOT, capture_output=True, text=True, timeout=120)
	if result.returncode:
		raise ValueError(f"MECHANICAL_FAILURE: workbook build failed; prior version preserved. {result.stderr[-1000:]}")
	snapshot = read_snapshot(snapshot_path)
	_assert_mechanical(snapshot)
	return snapshot


def _load_analysis(run_dir: Path) -> tuple[dict, dict, dict, dict]:
	"""Validate the accepted artifact's financial/source identity, not old code timestamps."""
	manifest = read(run_dir / "workflow-manifest.json")
	context = read(run_dir / "review-context.json")
	effective = read(run_dir / "effective-model.json")
	review = read(Path(effective["review_path"]))
	if effective["status"] != "SYSTEM_REVIEWED" or effective["human_approval"] or content_hash(review) != effective["review_hash"]:
		raise ValueError("Accepted analysis review binding is invalid")
	if content_hash(context) != manifest["context_hash"] or context["bindings"] != manifest["bindings"]:
		raise ValueError("STALE_CONTEXT: accepted review context changed")
	for key, value in manifest["bindings"].items():
		if key in manifest["input_paths"] and digest(Path(manifest["input_paths"][key])) != value:
			raise ValueError(f"STALE_CONTEXT: accepted input changed: {key}")
	if digest(Path(effective["model_path"])) != effective["model_sha256"]:
		raise ValueError("STALE_CONTEXT: accepted model changed")
	validate_review(review, source_allowlist=set(context["source_ref_allowlist"]), source_records=context["source_records"])
	if review["verdict"] != "accept":
		raise ValueError("A complete accepted analysis is required before P11 export")
	return manifest, context, effective, review


def _metadata(model: dict, *, context: dict, review: dict, manifest: dict, financial_snapshot: dict, version: str, prior_version: str | None = None, revision_review: dict | None = None, revision_request_hash: str | None = None) -> dict:
	sources = []
	for key, row in context["source_records"].items():
		source_path = Path(row.get("source_path") or Path(manifest["input_paths"]["calculated_context"]).with_name("review-context.json"))
		if not source_path.is_absolute():
			source_path = ROOT / source_path
		sources.append({"source_id": key, "period": str(row.get("period") or "explicit estimate"), "cutoff": context["information_cutoff"], "kind": row["kind"], "excerpt": row.get("excerpt") or "Identity record; full evidence is referenced separately.", "source_file": str(source_path), "locator": row.get("locator") or f"review-context.json#/source_records/{key}", "sha256": digest(source_path)})
	areas = [{"area": area["area"], "outcome": area["outcome"], "basis": area["basis"], "changed_dependencies": area["changed_dependencies_assessed"], "decision_refs": [f"AREA-PACKET:{area['area']}"], "source_refs": area["source_refs"], "limitations": area["concerns"]} for area in review["areas"]]
	if revision_review:
		area = next(row for row in areas if row["area"] == "dcf_terminal")
		area["basis"] = revision_review["rationale"]
		area["limitations"] = revision_review["concerns"]
	inputs = []
	for key, address, units, source in [
		("risk_free_rate", "B12", "decimal annual rate", "MKT-RF-10Y"),
		("equity_risk_premium", "B13", "decimal annual premium", "MKT-ERP"),
		("beta", "B14", "unitless", "MKT-BETA"),
		("debt_spread", "B15", "decimal annual spread", "MKT-CREDIT-AAA"),
		("debt_tax_shield_rate", "B16", "decimal tax rate", "FILING:0001193125-26-191507:taxes"),
		("terminal_growth", "B27", "decimal annual growth", "AREA-PACKET:dcf_terminal"),
	]:
		inputs.append({"address": f"Valuation!{address}", "label": key.replace("_", " "), "exported_value": model["valuation_policy"][key], "units": units, "classification": "selected estimate or dated proxy", "area": "dcf_terminal", "decision_refs": ["AREA-PACKET:dcf_terminal"], "source_refs": [source], "rationale": areas[-1]["basis"], "caveat": "Exported base rationale. Local edits recalculate but require authoritative CLI review; estimates are not reported forward facts."})
	capex = next(item["value"] for item in model["candidate"]["parameters"] if item["name"] == "cash_ppe_additions_rate")
	inputs.append({"address": "Inputs!B32", "label": "Cash PP&E additions / revenue", "exported_value": capex, "units": "decimal of revenue", "classification": "selected forecast estimate from historical cash ratio", "area": "ppe_capex", "decision_refs": ["AREA-PACKET:ppe_capex"], "source_refs": ["FILING:0001193125-26-191507:ppe_supplier", "FILING:0001193125-26-191507:cash_flows"], "rationale": next(area["basis"] for area in areas if area["area"] == "ppe_capex"), "caveat": "Exported base estimate; supplier noncash additions and leases are separate. Local edits invalidate attached reasoning."})
	return {
		"schema_version": "p11-review-metadata-v1",
		"review": {"id": content_hash(revision_review or review), "version": "P11" if revision_review else "P10", "verdict": "accept", "completed_at": now(), "independent_recheck_id": content_hash(revision_review) if revision_review else None},
		"states": {"execution": "ANALYTICAL_COMPLETE", "mechanical": "PASS", "coverage": "COMPLETE", "analytical": "RECHECK_ACCEPTED" if revision_review else "REVIEW_ACCEPTED", "budget": "AVAILABLE; see cost-receipt.json beside workbook", "human": False},
		"bindings": {"selected_model_sha256": content_hash(model), "financial_snapshot_sha256": content_hash(_financial_values(financial_snapshot)), "financial_snapshot_hash_basis": "financial-values-v1", "review_request_sha256": revision_request_hash or manifest["request_hash"], "review_response_sha256": content_hash(revision_review or review), "source_context_sha256": manifest["context_hash"]},
		"provenance": {"run_id": manifest["request_hash"][:16], "authoritative_version": version, "prior_version": prior_version, "exported_at": now()},
		"narrative": {"summary": revision_review["rationale"] if revision_review else review["rationale"], "key_drivers": "Segment growth; consolidated functional costs; cash and noncash investment; asset lives; WACC and normalized terminal reinvestment.", "cash_vs_ufcf": "Cash FCF = CFO minus cash PP&E payments. Economic UFCF additionally separates financing/tax/SBC effects and includes noncash productive investment. Future accumulated cash is not added to DCF value again.", "limitations": ["Later-informed development valuation: measurement 2026-03-31, source cutoff 2026-04-30; not a point-in-time backtest.", "Segment cost of revenue and aggregate operating expenses ARE disclosed; consolidated functional ratios are an explicit modeling choice.", "Historical full UFCF is not completely estimated where source detail is unavailable.", "Beta, growth, lives, reinvestment, tax timing and several claim treatments remain estimates. Human financial approval remains outstanding."]},
		"areas": areas, "sources": sources, "material_inputs": inputs,
	}


def export_base(analysis_run: Path, output_dir: Path) -> dict:
	manifest, context, effective, review = _load_analysis(analysis_run)
	model = read(Path(effective["model_path"]))
	baseline = read(Path(manifest["input_paths"]["calculated_context"]))["snapshot"]
	version_id = "v1-" + manifest["request_hash"][:12]
	metadata = _metadata(model, context=context, review=review, manifest=manifest, financial_snapshot=baseline, version=version_id)
	return _publish(model, metadata, baseline, output_dir, analysis_run, version_id, None, {}, expected_prior_sha256=None)


def _publish_artifacts(model: dict, metadata: dict, baseline: dict, output_dir: Path, analysis_run: Path, version_id: str, prior: str | None, choices: dict, *, allow_recovery: bool = False) -> dict:
	metadata = {**metadata, "bindings": {**metadata["bindings"], "user_choices_sha256": content_hash(choices)}}
	output_dir = output_dir.resolve()
	if output_dir.exists() and any(output_dir.iterdir()):
		if not allow_recovery:
			raise ValueError("Output directory is not empty; published and edited copies are preserved")
		if (output_dir / "version.json").exists():
			existing = validate_version(output_dir)
			published_model = read(Path(existing["model_path"]))
			published_metadata = published_model.pop("review_metadata")
			if published_model != model or published_metadata["bindings"] != metadata["bindings"] or published_metadata["review"]["id"] != metadata["review"]["id"] or existing["version"] != version_id or existing["prior_version"] != prior or existing["user_choices"] != choices:
				raise ValueError("Existing published version differs; preserved without replacement")
			return existing
		# One bounded recovery destination; never overwrite a partially built or edited copy.
		recovery = output_dir.with_name(output_dir.name + "-recovery")
		return _publish_artifacts(model, metadata, baseline, recovery, analysis_run, version_id, prior, choices, allow_recovery=(recovery / "version.json").exists())
	model_path = output_dir / "reviewed-model.json"
	workbook_path = output_dir / "MSFT-review.xlsx"
	snapshot_path = output_dir / "calculated-snapshot.json"
	write_new(model_path, {**model, "review_metadata": metadata})
	actual = _build(model_path, workbook_path, snapshot_path)
	if _financial_values(actual) != _financial_values(baseline):
		raise ValueError("MECHANICAL_FAILURE: review export changed financial values; no version published")
	version = {"version": version_id, "status": "SYSTEM_REVIEWED", "human_approval": False, "prior_version": prior, "analysis_run": str(analysis_run.resolve()), "model_path": str(model_path), "model_sha256": digest(model_path), "workbook_path": str(workbook_path), "workbook_sha256": digest(workbook_path), "snapshot_path": str(snapshot_path), "snapshot_sha256": digest(snapshot_path), "review_metadata_hash": content_hash(metadata), "user_choices": choices, "per_share_value": actual["p9"]["perShareValue"], "created_at": now()}
	ledger_path = ROOT / "data/build-guide-api-budget.json"
	ledger = read(ledger_path)
	receipt = {"purpose": "Program API cost checkpoint at this workbook export", "recorded_at": now(), "ledger_path": str(ledger_path), "ledger_sha256": digest(ledger_path), "ceiling_eur": ledger["ceiling_eur"], "final_review_reserve_eur": ledger["final_review_reserve_eur"], "known_eur": sum(call.get("cost", {}).get("priced_eur", 0) for call in ledger["calls"]), "unknown_usage_holds_eur": sum(call["reserved_eur"] for call in ledger["calls"] if not call.get("cost")), "calls": [{key: call.get(key) for key in ("call_id", "task_id", "request_hash", "status", "cost", "reserved_eur")} for call in ledger["calls"]], "basis": "Provider-reported tokens at each admitted dated price/FX snapshot; unknown-usage holds remain reserved. Not an asserted invoice total."}
	write_new(output_dir / "cost-receipt.json", receipt)
	version["cost_receipt_sha256"] = digest(output_dir / "cost-receipt.json")
	write_new(output_dir / "version.json", version)
	return version


def _publish(model: dict, metadata: dict, baseline: dict, output_dir: Path, analysis_run: Path, version_id: str, prior: str | None, choices: dict, *, expected_prior_sha256: str | None, allow_recovery: bool = False) -> dict:
	"""Publish immutable artifacts and advance the authoritative pointer under one lock."""
	with _publication_lock():
		current = _current_pointer()
		if prior is None:
			if current is not None:
				raise ValueError("STALE_CONTEXT: an authoritative base version is already current")
		elif expected_prior_sha256 is None:
			raise ValueError("Expected prior-version hash is required for a revision publication")
		elif current is None or current["version"] != prior or current["version_sha256"] != expected_prior_sha256:
			raise ValueError("STALE_CONTEXT: expected prior version is no longer current")
		published = _publish_artifacts(model, metadata, baseline, output_dir, analysis_run, version_id, prior, choices, allow_recovery=allow_recovery)
		validated = validate_version(Path(published["model_path"]).parent)
		_atomic_current(_pointer_for(validated))
	return validate_version(Path(published["model_path"]).parent)


def validate_version(version_dir: Path) -> dict:
	version = read(version_dir / "version.json")
	for name in ("model", "workbook", "snapshot"):
		if digest(Path(version[f"{name}_path"])) != version[f"{name}_sha256"]:
			raise ValueError(f"STALE_CONTEXT: {name} changed. Excel edits are not silently imported; use the preserved authoritative version.")
	if version["status"] != "SYSTEM_REVIEWED" or version["human_approval"]:
		raise ValueError("Invalid authoritative review version")
	manifest, _, _, _ = _load_analysis(Path(version["analysis_run"]))
	model = read(Path(version["model_path"]))
	metadata = model.pop("review_metadata")
	snapshot_artifact = read(Path(version["snapshot_path"]))
	snapshot = read_snapshot(Path(version["snapshot_path"]))
	bindings = metadata["bindings"]
	if content_hash(metadata) != version["review_metadata_hash"] or metadata["provenance"]["authoritative_version"] != version["version"] or metadata["provenance"]["prior_version"] != version["prior_version"]:
		raise ValueError("STALE_CONTEXT: review metadata or version identity changed")
	if bindings.get("financial_snapshot_hash_basis") != "financial-values-v1" or bindings["selected_model_sha256"] != content_hash(model) or bindings["financial_snapshot_sha256"] != content_hash(_financial_values(snapshot)) or bindings["source_context_sha256"] != manifest["context_hash"]:
		raise ValueError("STALE_CONTEXT: reviewed financial or source bindings changed")
	if bindings["review_response_sha256"] != metadata["review"]["id"] or metadata["review"]["verdict"] != "accept" or metadata["states"]["human"] is not False:
		raise ValueError("STALE_CONTEXT: review identity or approval state changed")
	if bindings["user_choices_sha256"] != content_hash(version["user_choices"]):
		raise ValueError("STALE_CONTEXT: recorded user choices changed")
	for control, choice in version["user_choices"].items():
		if control not in CONTROLS or choice["value"] != model["valuation_policy"][control]:
			raise ValueError("STALE_CONTEXT: recorded user choice differs from the reviewed model")
	if snapshot_artifact["annotatedModelSha256"] != version["model_sha256"] or snapshot_artifact["selectedFinancialModelSha256"] != bindings["selected_model_sha256"] or snapshot_artifact["authoritativeVersion"] != version["version"] or snapshot_artifact["reviewId"] != metadata["review"]["id"]:
		raise ValueError("STALE_CONTEXT: snapshot review/model identity changed")
	if snapshot_artifact["workbookSha256"] != version["workbook_sha256"]:
		raise ValueError("Snapshot is not bound to the exported workbook")
	if digest(version_dir / "cost-receipt.json") != version["cost_receipt_sha256"]:
		raise ValueError("STALE_CONTEXT: exported cost receipt changed")
	if version["per_share_value"] != snapshot["p9"]["perShareValue"]:
		raise ValueError("STALE_CONTEXT: version headline differs from the reviewed calculation")
	_assert_mechanical(snapshot)
	current = _current_pointer()
	return {
		**version,
		"is_current": current is not None
		and Path(current["version_dir"]).resolve() == version_dir.resolve()
		and current["version_sha256"] == digest(version_dir / "version.json"),
		"current_version": current["version"] if current is not None else None,
	}


def _code_bindings() -> dict:
	return {str(path): digest(path) for path in [Path(__file__), ROOT / "src/smrik_fund/analysis_transport.py", ROOT / "scripts/spreadsheet_compat/export-review.mjs", ROOT / "scripts/spreadsheet_compat/asset_model.mjs", ROOT / "scripts/spreadsheet_compat/valuation.mjs"]}


def _request(proposal: dict, context: dict, review: dict, candidate: dict, base: dict) -> dict:
	refs = [key for key in context["source_records"] if key.startswith("MKT-")]
	refs += ["FILING:0001193125-26-191507:taxes", "FILING:0001193125-26-191507:debt", "FILING:0001193125-26-191507:leases", "FILING:0000950170-25-100235:asset_policy"]
	refs = list(dict.fromkeys([*refs, *proposal["source_refs"]]))
	if set(refs) - context["source_records"].keys():
		raise ValueError("Revision refers to source evidence missing from the review context")
	semantic_proposal = {key: proposal[key] for key in ("selection_id", "control", "current_value", "proposed_value", "units", "source_refs", "affected_decisions", "replaces_existing_choice", "financial_impact")}
	payload = {"prompt_version": PROMPT_VERSION, "proposal": semantic_proposal, "context_bindings": context["bindings"], "source_records": {key: context["source_records"][key] for key in refs}, "base_review": review, "base_valuation": {key: value for key, value in base["p9"].items() if key != "status"}, "candidate_statements": candidate["statements"], "candidate_valuation": {key: value for key, value in candidate["p9"].items() if key != "status"}, "mechanical": {"all_period": candidate["allPeriodStatus"], "checks": candidate["checks"]}, "case": {key: context[key] for key in ("case", "measurement_date", "information_cutoff", "basis")}}
	return {"model": "gpt-5.6-sol", "reasoning": {"effort": "high"}, "service_tier": "default", "input": "Independently recheck this confirmed, supported valuation-input revision. The requested beta or terminal growth is an explicit development/user scenario, not a newly measured reported fact. Assess source/period/method validity, all affected valuation/terminal/claim dependencies, unchanged statement values and no double counting. Do not replace the requested value or output code/tools. Accept only a valid recalculated candidate; reject consequential unresolved concerns. Bind area=dcf_terminal and the supplied selection_id exactly. Human financial approval remains separate.\n" + json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\nUse concerns only for unresolved consequential blockers. Put accepted estimate caveats in rationale. The proposed value is an explicit scenario; acceptance does not certify that it is the uniquely correct forecast.", "text": {"format": {"type": "json_schema", "name": "p11_known_revision_review", "strict": True, "schema": _strict_schema(IndependentRecheck)}}, "max_output_tokens": 8000, "tools": [], "background": False}


def propose_revision(version_dir: Path, output_dir: Path, *, control: str | None = None, value: float | None = None, instruction: str | None = None, prices: dict) -> dict:
	version = validate_version(version_dir)
	_require_current(version_dir, version["version"], digest(version_dir / "version.json"))
	if instruction is not None:
		parsed = parse_instruction(instruction)
		if parsed["kind"] == "research":
			manifest = read(Path(version["analysis_run"]) / "workflow-manifest.json")
			if len(parsed["question"]) > 160:
				raise ValueError("Use a literal research phrase of at most 160 characters")
			query = EvidenceRequest(question_id="p11-" + content_hash(parsed)[:16], question=parsed["question"], literal_phrases=[parsed["question"]], followup_index=0)
			evidence = retrieve_evidence(Path(manifest["input_paths"]["source_manifest"]), query)
			result = {**parsed, "version": version["version"], "human_approval": False, "evidence": evidence, "next": "Literal filing matches are evidence to assess, not automatic financial conclusions. No model change or paid call occurred."}
			write_new(output_dir / "research-request.json", result)
			return result
		control, value = parsed["control"], parsed["value"]
	if control not in CONTROLS or value is None or isinstance(value, bool) or not math.isfinite(value):
		raise ValueError("Specify a supported numeric control and finite value")
	spec = CONTROLS[control]
	if not spec["minimum"] <= value <= spec["maximum"]:
		raise ValueError(f"{control} must be within [{spec['minimum']}, {spec['maximum']}] {spec['units']}")
	model = read(Path(version["model_path"]))
	base_metadata = model.pop("review_metadata")
	current = model["valuation_policy"][control]
	if value == current:
		raise ValueError("Requested value equals the authoritative value; unchanged re-export needs no paid review")
	if output_dir.exists() and any(output_dir.iterdir()):
		raise ValueError("Proposal directory is not empty; prior proposal preserved")
	base = read_snapshot(Path(version["snapshot_path"]))
	selection_id = f"user_revision:{control}:{value:g}"
	model["valuation_policy"][control] = value
	model["_p11_revision"] = {"base_version": version["version"], "control": control, "value": value, "selection_id": selection_id}
	output_dir = output_dir.resolve()
	model_path = output_dir / "candidate-model.json"
	write_new(model_path, model)
	try:
		candidate = _build(model_path, output_dir / "candidate.xlsx", output_dir / "candidate-snapshot.json")
	except Exception as exc:
		write_new(output_dir / "outcome.json", {"status": "FAILED_CANDIDATE", "reason": str(exc), "prior_version_preserved": True, "human_approval": False})
		raise
	if _financial_values(candidate)["statements"] != _financial_values(base)["statements"]:
		raise ValueError("MECHANICAL_FAILURE: this valuation-only revision changed a statement")
	proposal = {"status": "AWAITING_CONFIRMATION", "selection_id": selection_id, "base_version": version["version"], "base_version_dir": str(version_dir.resolve()), "base_version_sha256": digest(version_dir / "version.json"), "candidate_model_sha256": digest(model_path), "candidate_snapshot_sha256": digest(output_dir / "candidate-snapshot.json"), "candidate_workbook_sha256": digest(output_dir / "candidate.xlsx"), "control": control, "current_value": current, "proposed_value": value, "units": spec["units"], "source_refs": [spec["source"]], "rationale": instruction or f"Explicit numeric scenario: {control} {current:g} -> {value:g}", "affected_decisions": ["dcf_terminal"], "expected_scope": "Beta changes WACC, discounted cash flows and per-share value; growth changes normalized terminal cohorts and terminal value. All 550 statement values remain unchanged.", "replaces_existing_choice": version["user_choices"].get(control), "mechanical": "PASS", "financial_impact": {key: {"current": base["p9"][key], "proposed": candidate["p9"][key], "change": candidate["p9"][key] - base["p9"][key]} for key in ("wacc", "enterpriseValue", "commonEquityValue", "perShareValue")}, "human_approval": False}
	manifest, context, _, review = _load_analysis(Path(version["analysis_run"]))
	current_review = {"review_id": base_metadata["review"]["id"], "areas": base_metadata["areas"], "rationale": base_metadata["narrative"]["summary"], "status": base_metadata["states"]["analytical"], "original_whole_model_review": content_hash(review)}
	request = _request(proposal, context, current_review, candidate, base)
	proposal["request_hash"] = content_hash(request)
	proposal["price_estimate"] = reservation(request, prices)
	proposal["code_bindings"] = _code_bindings()
	proposal["source_context_hash"] = manifest["context_hash"]
	write_new(output_dir / "review-request.json", request)
	write_new(output_dir / "proposal.json", proposal)
	return proposal


def _validate_proposal(proposal_dir: Path, proposal: dict) -> tuple[dict, dict]:
	"""Bind the displayed change to the base, actual candidate and exact paid request."""
	version_dir = Path(proposal["base_version_dir"])
	version = validate_version(version_dir)
	if content_hash(read(proposal_dir / "proposal.json")) != content_hash(proposal):
		raise ValueError("STALE_CONTEXT: proposal changed during confirmation")
	if digest(version_dir / "version.json") != proposal["base_version_sha256"] or _code_bindings() != proposal["code_bindings"]:
		raise ValueError("STALE_CONTEXT: version or implementation changed after the proposal")
	for name, filename in (("model", "candidate-model.json"), ("snapshot", "candidate-snapshot.json"), ("workbook", "candidate.xlsx")):
		if digest(proposal_dir / filename) != proposal[f"candidate_{name}_sha256"]:
			raise ValueError("STALE_CONTEXT: candidate changed after the proposal")
	request = read(proposal_dir / "review-request.json")
	if content_hash(request) != proposal["request_hash"]:
		raise ValueError("STALE_CONTEXT: revision review request changed")
	control, value = proposal["control"], proposal["proposed_value"]
	if control not in CONTROLS or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
		raise ValueError("STALE_CONTEXT: proposal has an unsupported control or value")
	spec = CONTROLS[control]
	if not spec["minimum"] <= value <= spec["maximum"]:
		raise ValueError("STALE_CONTEXT: proposed value is outside supported bounds")
	model = read(Path(version["model_path"]))
	base_metadata = model.pop("review_metadata")
	current = model["valuation_policy"][control]
	base = read_snapshot(Path(version["snapshot_path"]))
	candidate = read_snapshot(proposal_dir / "candidate-snapshot.json")
	_assert_mechanical(candidate)
	selection_id = f"user_revision:{control}:{value:g}"
	expected_fields = {"status": "AWAITING_CONFIRMATION", "base_version": version["version"], "selection_id": selection_id, "current_value": current, "units": spec["units"], "source_refs": [spec["source"]], "affected_decisions": ["dcf_terminal"], "replaces_existing_choice": version["user_choices"].get(control), "mechanical": "PASS", "human_approval": False, "financial_impact": {key: {"current": base["p9"][key], "proposed": candidate["p9"][key], "change": candidate["p9"][key] - base["p9"][key]} for key in ("wacc", "enterpriseValue", "commonEquityValue", "perShareValue")}}
	if value == current or any(proposal[key] != expected for key, expected in expected_fields.items()):
		raise ValueError("STALE_CONTEXT: proposal semantics differ from the authoritative revision")
	model["valuation_policy"][control] = value
	model["_p11_revision"] = {"base_version": version["version"], "control": control, "value": value, "selection_id": selection_id}
	if model != read(proposal_dir / "candidate-model.json") or _financial_values(candidate)["statements"] != _financial_values(base)["statements"]:
		raise ValueError("STALE_CONTEXT: candidate does not implement exactly the displayed valuation change")
	candidate_artifact = read(proposal_dir / "candidate-snapshot.json")
	if candidate_artifact["annotatedModelSha256"] != proposal["candidate_model_sha256"] or candidate_artifact["workbookSha256"] != proposal["candidate_workbook_sha256"]:
		raise ValueError("STALE_CONTEXT: candidate snapshot is not bound to its model and workbook")
	manifest, context, _, review = _load_analysis(Path(version["analysis_run"]))
	current_review = {"review_id": base_metadata["review"]["id"], "areas": base_metadata["areas"], "rationale": base_metadata["narrative"]["summary"], "status": base_metadata["states"]["analytical"], "original_whole_model_review": content_hash(review)}
	if proposal["source_context_hash"] != manifest["context_hash"] or _request(proposal, context, current_review, candidate, base) != request:
		raise ValueError("STALE_CONTEXT: paid request does not match the proposal and reviewed evidence")
	return version, request


def _matching_published_candidate(proposal_dir: Path, proposal: dict, version: dict) -> dict | None:
	"""Return only the exact already-current publication for an interrupted retry."""
	current = _current_pointer()
	if current is None:
		return None
	expected_version = f"v{int(version['version'].split('-')[0][1:]) + 1}-" + proposal["request_hash"][:12]
	allowed_dirs = {
		(proposal_dir / "reviewed-version").resolve(),
		(proposal_dir / "reviewed-version-recovery").resolve(),
	}
	current_dir = Path(current["version_dir"]).resolve()
	if current["version"] != expected_version or current_dir not in allowed_dirs:
		return None
	published = validate_version(current_dir)
	model = read(Path(published["model_path"]))
	metadata = model.pop("review_metadata")
	if (
		model != read(proposal_dir / "candidate-model.json")
		or published["prior_version"] != version["version"]
		or metadata["bindings"]["review_request_sha256"] != proposal["request_hash"]
		or metadata["review"]["id"] != content_hash(read(proposal_dir / "independent-review.json"))
	):
		raise ValueError("STALE_CONTEXT: current publication differs from this reviewed candidate")
	return published


def confirm_revision(proposal_dir: Path, *, prices: dict, budget_path: Path, development_confirmation: bool = False, reject: bool = False, client: Any = None) -> dict:
	proposal = read(proposal_dir / "proposal.json")
	version, request = _validate_proposal(proposal_dir, proposal)
	terminal_path = proposal_dir / "outcome.json"
	if terminal_path.exists():
		outcome = read(terminal_path)
		if outcome.get("version_dir"):
			published = _matching_published_candidate(proposal_dir, proposal, version)
			if published is None or Path(outcome["version_dir"]).resolve() != Path(published["model_path"]).parent.resolve():
				raise ValueError("STALE_CONTEXT: completed outcome is no longer the current publication")
		return outcome
	confirmation_path = proposal_dir / "confirmation.json"
	confirmation = {"proposal_hash": content_hash(proposal), "action": "decline" if reject else "confirm_for_review", "actor": "development_agent" if development_confirmation else "cli_user", "human_financial_approval": False}
	if confirmation_path.exists():
		if {key: value for key, value in read(confirmation_path).items() if key != "timestamp"} != confirmation:
			raise ValueError("Existing confirmation differs; prepare a new proposal")
	else:
		write_new(confirmation_path, {**confirmation, "timestamp": now()})
	if reject:
		_require_current(Path(proposal["base_version_dir"]), version["version"], proposal["base_version_sha256"])
		outcome = {"status": "DECLINED", "prior_version_preserved": True, "human_approval": False}
		write_new(terminal_path, outcome)
		return outcome
	published = _matching_published_candidate(proposal_dir, proposal, version)
	if published is not None:
		transport_path = proposal_dir / "review-transport.json"
		outcome = {"status": "ADOPTED_NEW_VERSION", "version": published["version"], "version_dir": str(Path(published["model_path"]).parent), "per_share_value": published["per_share_value"], "prior_version_preserved": True, "human_approval": False, "transport": read(transport_path) if transport_path.exists() else {"status": "completed-replay"}}
		write_new(terminal_path, outcome)
		return outcome
	_require_current(Path(proposal["base_version_dir"]), version["version"], proposal["base_version_sha256"])
	raw_review, metadata = dispatch_request(request, run_dir=proposal_dir, stage="independent_recheck", budget_path=budget_path, prices=prices, package="p11", client=client)
	recheck = IndependentRecheck.model_validate(raw_review)
	write_new(proposal_dir / "independent-review.json", raw_review)
	# Replay is a property of this access, not of the immutable provider result.
	write_new(proposal_dir / "review-transport.json", {key: value for key, value in metadata.items() if key != "resumed"})
	if recheck.area != "dcf_terminal" or recheck.selection_id != proposal["selection_id"]:
		raise ValueError("Independent reviewer changed the requested revision")
	accepted = recheck.verdict == "accept" and not recheck.concerns and all((recheck.source_valid, recheck.period_valid, recheck.method_valid, recheck.no_double_count, recheck.cross_schedule_concerns_resolved))
	if not accepted:
		outcome = {"status": "REJECTED", "review": raw_review, "transport": metadata, "prior_version_preserved": True, "human_approval": False}
	else:
		# Revalidate after the paid stage so concurrent edits cannot be adopted.
		_validate_proposal(proposal_dir, proposal)
		model = read(proposal_dir / "candidate-model.json")
		candidate = read_snapshot(proposal_dir / "candidate-snapshot.json")
		manifest, context, _, review = _load_analysis(Path(version["analysis_run"]))
		version_id = f"v{int(version['version'].split('-')[0][1:]) + 1}-" + proposal["request_hash"][:12]
		review_metadata = _metadata(model, context=context, review=review, manifest=manifest, financial_snapshot=candidate, version=version_id, prior_version=version["version"], revision_review=raw_review, revision_request_hash=proposal["request_hash"])
		choices = {**version["user_choices"], proposal["control"]: {"value": proposal["proposed_value"], "actor": "development_agent" if development_confirmation else "cli_user"}}
		published = _publish(model, review_metadata, candidate, proposal_dir / "reviewed-version", Path(version["analysis_run"]), version_id, version["version"], choices, expected_prior_sha256=proposal["base_version_sha256"], allow_recovery=True)
		outcome = {"status": "ADOPTED_NEW_VERSION", "version": published["version"], "version_dir": str(Path(published["workbook_path"]).parent), "per_share_value": published["per_share_value"], "prior_version_preserved": True, "human_approval": False, "transport": metadata}
	write_new(terminal_path, outcome)
	return outcome


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	sub = parser.add_subparsers(dest="command", required=True)
	export = sub.add_parser("export")
	export.add_argument("--analysis-run", type=Path, required=True)
	export.add_argument("--output-dir", type=Path, required=True)
	propose = sub.add_parser("propose")
	propose.add_argument("--version-dir", type=Path, required=True)
	propose.add_argument("--output-dir", type=Path, required=True)
	propose.add_argument("--input", choices=CONTROLS, dest="control")
	propose.add_argument("--value", type=float)
	propose.add_argument("--instruction")
	confirm = sub.add_parser("confirm")
	confirm.add_argument("--proposal-dir", type=Path, required=True)
	confirm.add_argument("--development-confirmation", action="store_true")
	confirm.add_argument("--reject", action="store_true")
	status = sub.add_parser("status")
	status.add_argument("--version-dir", type=Path, required=True)
	for command in (propose, confirm):
		command.add_argument("--prices", type=Path, default=ROOT / "data/build-guide-p10/parent-preflight/sol-price-snapshot.json")
	confirm.add_argument("--budget", type=Path, default=ROOT / "data/build-guide-api-budget.json")
	args = parser.parse_args(argv)
	try:
		if args.command == "export":
			result = export_base(args.analysis_run.resolve(), args.output_dir.resolve())
		elif args.command == "propose":
			if args.instruction is not None and (args.control is not None or args.value is not None):
				raise ValueError("Use a numeric change or a natural-language instruction, not both")
			result = propose_revision(args.version_dir.resolve(), args.output_dir.resolve(), control=args.control, value=args.value, instruction=args.instruction, prices=read(args.prices))
		elif args.command == "confirm":
			result = confirm_revision(args.proposal_dir.resolve(), prices=read(args.prices), budget_path=args.budget.resolve(), development_confirmation=args.development_confirmation, reject=args.reject)
		else:
			result = validate_version(args.version_dir.resolve())
		print(json.dumps(result, indent=2, ensure_ascii=False))
		return 0 if result.get("status") not in {"REJECTED", "FAILED_CANDIDATE"} else 2
	except (ValueError, KeyError, OSError, subprocess.TimeoutExpired) as exc:
		print(json.dumps({"status": "BLOCKED", "reason": str(exc), "prior_version_preserved": True, "human_approval": False}))
		return 2


if __name__ == "__main__":
	raise SystemExit(main())

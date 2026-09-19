"""Bounded analyst -> calculated company model -> independent review -> Excel."""

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from smrik_fund.analysis_budget import content_hash, record_outcome, reserve_call
from smrik_fund.analysis_transport import _structured_response
from smrik_fund.company_case import freeze_company, validate_case
from smrik_fund.company_model import CONTROL_BOUNDS, validate_controls
from smrik_fund.portable_model import prepare_model
from smrik_fund.workbook_template import DEFAULT_TEMPLATE, compile_template

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "scripts/spreadsheet_compat/company-workbook.mjs"
FORMATTER = ROOT / "scripts/spreadsheet_compat/format-company-workbook.ps1"


def read(path):
	return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
	path = Path(path)
	if path.exists():
		if read(path) != json.loads(json.dumps(value)):
			raise ValueError(f"Immutable checkpoint changed: {path.name}")
		return
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("x", encoding="utf-8") as stream:
		json.dump(value, stream, indent=2, allow_nan=False)
		stream.write("\n")


def fingerprint(path):
	return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def schema(review=False, control_names=None):
	control_names = list(control_names or CONTROL_BOUNDS)
	controls = {
		"type": "object",
		"properties": {key: {"type": "number"} for key in control_names},
		"required": control_names,
		"additionalProperties": False,
	}
	properties = {
		"controls": controls,
		"rationale": {"type": "string"},
		"limitations": {"type": "array", "items": {"type": "string"}},
	}
	if review:
		properties["verdict"] = {
			"type": "string",
			"enum": ["accept", "revise", "reject"],
		}
	return {
		"type": "object",
		"properties": properties,
		"required": list(properties),
		"additionalProperties": False,
	}


def call_model(output_dir, name, payload, *, review, budget_path, prices, client=None):
	"""No hidden retries; save raw response and settle usage before semantic gates."""
	request = {
		"model": prices["model"],
		"service_tier": "default",
		"reasoning": {"effort": "high" if review else "medium"},
		"max_output_tokens": 12000 if review else 4000,
		"tools": [],
		"background": False,
		"input": json.dumps(payload, ensure_ascii=False),
		"text": {
			"format": {
				"type": "json_schema",
				"name": "company_review" if review else "company_assumptions",
				"strict": True,
				"schema": schema(review, payload.get("model", {}).get("controls")),
			}
		},
	}
	request_path = output_dir / f"{name}.request.json"
	response_path = output_dir / f"{name}.response.json"
	receipt_path = output_dir / f"{name}.receipt.json"
	save(request_path, request)
	call_id = (
		"company-"
		+ content_hash(
			{"output": str(output_dir.resolve()), "name": name, "request": request}
		)[:24]
	)
	if response_path.exists():
		if read(receipt_path) != {
			"request_hash": content_hash(request),
			"response_sha256": fingerprint(response_path),
			"call_id": call_id,
		}:
			raise ValueError("Saved response/request binding changed")
		raw = read(response_path)
	else:
		if client is None:
			from dotenv import load_dotenv
			from openai import OpenAI

			load_dotenv(ROOT / ".env")
			client = OpenAI(max_retries=0, timeout=300 if review else 180)
		if urlparse(str(client.base_url)).hostname != "api.openai.com":
			raise ValueError("Configured endpoint differs from verified price snapshot")
		state = read(budget_path)
		if any(item["call_id"] == call_id for item in state["calls"]):
			raise ValueError(
				"Prior attempt has unknown transport outcome; reservation preserved, no automatic retry"
			)
		reserve_call(
			budget_path,
			call_id=call_id,
			task_id="second-company-e2e",
			request=request,
			endpoint_host="api.openai.com",
			final_review=review,
			prices=prices,
		)
		started = time.monotonic()
		try:
			raw = client.responses.create(**request).model_dump(mode="json")
			save(response_path, raw)
			save(
				receipt_path,
				{
					"request_hash": content_hash(request),
					"response_sha256": fingerprint(response_path),
					"call_id": call_id,
				},
			)
		except Exception:
			record_outcome(
				budget_path,
				call_id=call_id,
				usage=None,
				elapsed_seconds=time.monotonic() - started,
			)
			raise
		finally:
			save(
				output_dir / f"{name}.elapsed.json",
				{"seconds": time.monotonic() - started},
			)
	state = read(budget_path)
	call = next(item for item in state["calls"] if item["call_id"] == call_id)
	if call["status"] != "completed":
		record_outcome(
			budget_path,
			call_id=call_id,
			usage=raw.get("usage"),
			elapsed_seconds=read(output_dir / f"{name}.elapsed.json")["seconds"],
			response_id=raw.get("id"),
			returned_model=raw.get("model"),
		)
	result = _structured_response(raw)
	validate_controls(result["controls"])
	if review and result.get("verdict") not in {"accept", "revise", "reject"}:
		raise ValueError("Invalid review verdict")
	save(output_dir / f"{name}.structured.json", result)
	return result


def build(model, output_dir):
	output_dir.mkdir(parents=True, exist_ok=True)
	save(output_dir / "model.json", model)
	if not (output_dir / "snapshot.json").exists():
		try:
			subprocess.run(
				[
					"node",
					str(ENGINE),
					str(output_dir / "model.json"),
					str(output_dir / f"{model['case']}.xlsx"),
					str(output_dir / "snapshot.json"),
				],
				check=True,
				capture_output=True,
				text=True,
				timeout=120,
			)
		except subprocess.CalledProcessError as exc:
			raise ValueError(
				"Workbook calculation stopped: " + (exc.stderr or str(exc))[-2400:]
			) from exc
	snapshot = read(output_dir / "snapshot.json")
	if snapshot["mechanical"] != "PASS" or snapshot["valuation_gate"] != "PASS":
		raise ValueError(
			"Calculated company model is blocked; inspect preserved snapshot"
		)
	return snapshot


def completed_analyst(run_dir, case_hash):
	"""Reuse a completed, bound analyst response; never retry unknown transport."""
	run_dir = Path(run_dir)
	request = read(run_dir / "analyst.request.json")
	receipt = read(run_dir / "analyst.receipt.json")
	if receipt["request_hash"] != content_hash(request) or receipt[
		"response_sha256"
	] != fingerprint(run_dir / "analyst.response.json"):
		raise ValueError("Saved analyst response/request binding changed")
	if json.loads(request["input"])["model"]["case_hash"] != case_hash:
		raise ValueError("Saved analyst uses a different source case")
	analyst = _structured_response(read(run_dir / "analyst.response.json"))
	validate_controls(analyst["controls"])
	return analyst


def run_case(
	ticker,
	case_dir,
	output_dir,
	*,
	live=False,
	beta=None,
	prior=None,
	budget_path=None,
	price_dir=None,
	native_excel=True,
	resume_from=None,
	assumptions=None,
	progress=None,
	template=None,
):
	def stage(name, status, detail):
		if progress is not None:
			progress(name, status, detail)

	if assumptions is not None:
		if live or prior or resume_from:
			raise ValueError("Operator assumptions require a new free run")
		if not isinstance(assumptions, dict) or set(assumptions) != {
			"controls",
			"rationale",
			"limitations",
		}:
			raise ValueError("Assumptions require controls, rationale and limitations")
		validate_controls(assumptions["controls"])
		if (
			not isinstance(assumptions["rationale"], str)
			or not assumptions["rationale"].strip()
			or not isinstance(assumptions["limitations"], list)
			or any(not isinstance(x, str) for x in assumptions["limitations"])
		):
			raise ValueError(
				"Assumptions require a nonempty rationale and text limitations"
			)
	if (beta is None) != (prior is None):
		raise ValueError("--beta and --prior must be supplied together")
	if resume_from and (prior or not live):
		raise ValueError("--resume-from requires --live and cannot accompany --prior")
	case_dir, output_dir = Path(case_dir).resolve(), Path(output_dir).resolve()
	manifest = validate_case(case_dir)
	if manifest["ticker"] != ticker.strip().upper():
		raise ValueError("Requested ticker differs from frozen company case")
	budget_path = Path(budget_path or ROOT / "data/build-guide-api-budget.json")
	price_dir = Path(price_dir or ROOT / "data/pricing/2026-09-10")
	template_path = Path(template or DEFAULT_TEMPLATE)
	if prior:
		# Numeric revisions retain the exact previously reviewed model structure.
		template_path = Path(prior) / "template.xlsx"
	patch = compile_template(template_path) if template_path.exists() else None
	if patch is None and not prior:
		raise ValueError(f"Model template missing: {template_path}")
	code = {
		str(path.relative_to(ROOT)): fingerprint(path)
		for path in (
			ENGINE,
			ROOT / "scripts/spreadsheet_compat/company-template.mjs",
			ROOT / "src/smrik_fund/workbook_template.py",
			ROOT / "scripts/spreadsheet_compat/company-statements.mjs",
			FORMATTER,
			Path(__file__),
			ROOT / "src/smrik_fund/company_model.py",
			ROOT / "src/smrik_fund/company_case.py",
			ROOT / "src/smrik_fund/portable_model.py",
			ROOT / "src/smrik_fund/company_history.py",
			ROOT / "src/smrik_fund/company_operating.py",
			ROOT / "src/smrik_fund/company_notes.py",
		)
	}
	save(
		output_dir / "run.json",
		{
			"ticker": ticker.upper(),
			"case_hash": content_hash(manifest),
			"code": code,
			"live": live,
			"template_sha256": patch["sha256"] if patch else None,
			"template_contract_sha256": patch["contract_sha256"] if patch else None,
			"beta_revision": beta,
			"prior": str(Path(prior).resolve()) if prior else None,
			"resume_from": str(Path(resume_from).resolve()) if resume_from else None,
		},
	)
	stage(
		"assembly",
		"RUNNING",
		"Assemble source-bound balances, history and forecast periods",
	)
	model = prepare_model(case_dir)
	if patch is not None:
		for source, destination, expected in (
			(template_path, output_dir / "template.xlsx", patch["sha256"]),
			(
				template_path.with_suffix(".json"),
				output_dir / "template.json",
				patch["contract_sha256"],
			),
		):
			if not destination.exists():
				shutil.copyfile(source, destination)
			if fingerprint(destination) != expected:
				raise ValueError(
					"Template changed while freezing the run; start a new run"
				)
		model["workbook_template"] = patch
		model["limitations"].append(patch["note"])
	stage("assembly", "PASS", "Source inputs assembled; reported values preserved")
	if assumptions is not None:
		save(output_dir / "operator-assumptions.json", assumptions)
	if prior:
		version = read(Path(prior) / "version.json")
		old_model = read(Path(prior) / "reviewed/model.json")
		if old_model.get("workbook_template") != patch:
			raise ValueError("Prior frozen template differs from its reviewed model")
		if (
			version["model_sha256"] != fingerprint(Path(prior) / "reviewed/model.json")
			or old_model["case_hash"] != model["case_hash"]
		):
			raise ValueError("Prior reviewed version or company source changed")
		if (
			version["workbook_sha256"]
			!= fingerprint(Path(prior) / f"reviewed/{model['case']}.xlsx")
			or version["snapshot_sha256"]
			!= fingerprint(Path(prior) / "reviewed/snapshot.json")
			or version["status"] != "SYSTEM_REVIEWED_DEVELOPMENT"
		):
			raise ValueError(
				"Prior workbook/snapshot changed or lacks independent review"
			)
		model = old_model
		model["controls"] = dict(old_model["controls"])
		if beta is None:
			raise ValueError("Numeric revision requires --beta")
		model["controls"]["beta"] = beta
		validate_controls(model["controls"])
		model["analyst"] = {
			"rationale": f"Authorized E2E beta revision to {beta}; prior assumptions retained.",
			"limitations": old_model["analyst"].get("limitations", []),
		}
	elif resume_from:
		prior_request = json.loads(
			read(Path(resume_from) / "analyst.request.json")["input"]
		)
		if prior_request["model"].get("workbook_template") != model.get(
			"workbook_template"
		):
			raise ValueError("Saved analyst uses a different Excel template")
		analyst = completed_analyst(resume_from, model["case_hash"])
		model["controls"].update(analyst["controls"])
		model["analyst"] = analyst
		save(
			output_dir / "analyst.reused.json",
			{
				"source": str(Path(resume_from).resolve()),
				"receipt_sha256": fingerprint(
					Path(resume_from) / "analyst.receipt.json"
				),
			},
		)
	elif live:
		analyst = call_model(
			output_dir,
			"analyst",
			{
				"task": "Propose conservative provisional controls for an E2E development valuation. User explicitly authorizes estimates/default simplifications for testing. Do not alter source values. These are not observed market inputs. Respect control bounds. Retain zero distributions when capital spending consumes operating cash; do not assume financing plugs. Keep assumptions coherent, explain major risks. PP&E/intangible horizon is a declining-carrying-balance time constant, not a straight-line vintage life. Share-price/diluted-share inputs are explicit proxies. Return all controls. Any workbook_template changes are operator-authored formulas applied before calculation; your authority is limited to supported controls.",
				"model": model,
			},
			review=False,
			budget_path=budget_path,
			prices=read(price_dir / "luna-price-snapshot.json"),
		)
		model["controls"].update(analyst["controls"])
		model["analyst"] = analyst
	elif assumptions is not None:
		model["controls"].update(assumptions["controls"])
		model["analyst"] = assumptions
		model["limitations"].extend(assumptions["limitations"])
	else:
		model["analyst"] = {
			"rationale": "Authorized provisional development defaults; no runtime analyst/review call.",
			"limitations": [],
		}
	stage(
		"calculation", "RUNNING", "Build linked statements, DCF and mechanical checks"
	)
	unsupported = set(model["controls"]) - set(model["control_bounds"])
	if unsupported:
		raise ValueError(
			f"Controls lack supported source methods: {sorted(unsupported)}"
		)
	snapshot = build(model, output_dir / "candidate-0")
	stage("calculation", "PASS", "Accounting, valuation and local-edit gates passed")
	review = {"status": "PROVISIONAL_UNREVIEWED", "human_approval": False}
	if live:
		for attempt in range(2):
			verdict = call_model(
				output_dir,
				f"review-{attempt}",
				{
					"task": "Independently review this provisional company DCF against source inputs and ALL calculated schedules. User authorizes estimates and simple development policies, not accounting errors. Check balance/cash/earnings links, D&A and SBC double counting, working capital, terminal reinvestment, claims/share proxy and source scope. Accept only a coherent explicitly qualified E2E scenario; acceptance is not investment/human approval. Reject substantive defects that controls cannot fix. For revise, return a complete corrected controls object; never change source facts. For accept, return current controls exactly. Explain limitations. Inspect workbook_template changes and calculated formula_examples: operator-authored formulas may change model mechanics. Reject incoherent edits that controls cannot fix.",
					"model": model,
					"calculated": snapshot,
				},
				review=True,
				budget_path=budget_path,
				prices=read(price_dir / "sol-price-snapshot.json"),
			)
			if verdict["verdict"] == "accept":
				if verdict["controls"] != model["controls"]:
					raise ValueError(
						"Accept response changes controls; a recalculation/review is required"
					)
				review = {
					**verdict,
					"status": "SYSTEM_REVIEWED_DEVELOPMENT",
					"human_approval": False,
				}
				break
			if verdict["verdict"] != "revise" or attempt == 1:
				raise ValueError(
					"Independent review did not accept; candidate and response preserved"
				)
			model["controls"] = verdict["controls"]
			snapshot = build(model, output_dir / "candidate-1")
	if any(fingerprint(ROOT / path) != expected for path, expected in code.items()):
		raise ValueError(
			"Implementation changed during the run; publication blocked, review evidence preserved"
		)
	model["review"] = review
	final = build(model, output_dir / "reviewed")
	if (
		final["schedules"] != snapshot["schedules"]
		or final["per_share_value"] != snapshot["per_share_value"]
	):
		raise ValueError("Review publication changed financial values")
	proof = output_dir / "native-excel-proof.json"
	stage(
		"excel",
		"RUNNING" if native_excel else "SKIPPED",
		"Native Excel formatting and recalculation"
		if native_excel
		else "Native Excel verification not requested",
	)
	if native_excel and not proof.exists():
		subprocess.run(
			[
				"powershell.exe",
				"-NoProfile",
				"-ExecutionPolicy",
				"Bypass",
				"-File",
				str(FORMATTER),
				"-WorkbookPath",
				str(output_dir / f"reviewed/{model['case']}.xlsx"),
				"-SnapshotPath",
				str(output_dir / "reviewed/snapshot.json"),
				"-ProofPath",
				str(proof),
			],
			check=True,
			capture_output=True,
			text=True,
			timeout=180,
		)
	if native_excel:
		stage(
			"excel",
			"PASS",
			"Native Excel formulas recalculated; beta edit and restoration checked",
		)
	version = {
		"ticker": model["case"],
		"template_sha256": model.get("workbook_template", {}).get("sha256"),
		"status": review["status"],
		"human_approval": False,
		"model_sha256": fingerprint(output_dir / "reviewed/model.json"),
		"workbook_sha256": fingerprint(output_dir / f"reviewed/{model['case']}.xlsx"),
		"snapshot_sha256": fingerprint(output_dir / "reviewed/snapshot.json"),
		"case_hash": model["case_hash"],
		"prior": str(Path(prior).resolve()) if prior else None,
		"per_share_value": final["per_share_value"],
	}
	if native_excel:
		version["native_excel_proof_sha256"] = fingerprint(proof)
	save(output_dir / "version.json", version)
	stage(
		"publication",
		"PASS",
		"Workbook and calculation hashes saved; " + review["status"],
	)
	return version


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("ticker")
	parser.add_argument("--case-dir", type=Path)
	parser.add_argument("--as-of", default="2026-09-10")
	parser.add_argument("--output-dir", required=True, type=Path)
	parser.add_argument(
		"--live",
		action="store_true",
		help="Run bounded paid analyst and independent review",
	)
	parser.add_argument("--prior", type=Path)
	parser.add_argument("--beta", type=float)
	parser.add_argument("--price-dir", type=Path)
	parser.add_argument("--resume-from", type=Path)
	args = parser.parse_args()
	case_dir = args.case_dir or args.output_dir / "source"
	if not (case_dir / "case.json").exists():
		freeze_company(args.ticker, args.as_of, case_dir)
	if validate_case(case_dir)["information_cutoff"] != args.as_of:
		raise ValueError("--as-of differs from frozen case cutoff")
	print(
		json.dumps(
			run_case(
				args.ticker,
				case_dir,
				args.output_dir,
				live=args.live,
				prior=args.prior,
				beta=args.beta,
				price_dir=args.price_dir,
				resume_from=args.resume_from,
			),
			indent=2,
		)
	)


if __name__ == "__main__":
	main()

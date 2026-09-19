"""Small localhost workbench: HTTP routes, durable free jobs, existing Typer commands.

No database, web framework, generic task engine or shell command builder. A job
is a JSON receipt plus a child Python process; it can finish if the browser closes.
"""

import json
import mimetypes
import os
import secrets
import subprocess
import sys
import threading
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from smrik_fund.market_screen import symbol
from smrik_fund.research_audit import (
	DATA_ROOT,
	audit_run,
	list_runs,
	read_json,
	within_data,
)

ROOT = Path(__file__).resolve().parents[2]
PAGE = Path(__file__).with_name("workbench.html")
ALLOWED_FILES = {
	"case.json",
	"filing.json",
	"source.txt",
	"balance_sheet.csv",
	"income_statement.csv",
	"cash_flow_statement.csv",
	"note_facts.csv",
	"model.json",
	"snapshot.json",
	"report.json",
	"screen.csv",
	"version.json",
	"run.json",
	"deep-inputs.json",
	"operator-assumptions.json",
	"native-excel-proof.json",
	"blocked.json",
	"deep-result.json",
	"events.jsonl",
	"index.html",
}


def save_job(path, value):
	"""Atomic replacement prevents polling from reading half-written receipts."""
	path.parent.mkdir(parents=True, exist_ok=True)
	temporary = path.with_suffix(".tmp")
	temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
	temporary.replace(path)


def jobs(data_root):
	rows = []
	for path in sorted((data_root / "workspace/jobs").glob("*.json"), reverse=True):
		value = read_json(path)
		# A killed worker cannot write its final receipt. Detect that condition
		# after a server restart, so an abandoned job does not lock the UI forever.
		if (
			value["status"] == "RUNNING"
			and value.get("pid")
			and not process_alive(value["pid"])
		):
			value.update(
				status="FAILED",
				reason="Worker stopped before writing a completion receipt; partial outputs retained.",
				finished_at=datetime.now(UTC).isoformat(),
			)
			save_job(path, value)
		log = path.with_suffix(".log")
		if log.exists():
			with log.open("rb") as stream:
				stream.seek(max(0, log.stat().st_size - 6000))
				value["log"] = stream.read().decode("utf-8", errors="replace")
		rows.append(value)
	return rows


def process_alive(pid):
	if sys.platform == "win32":
		import ctypes
		from ctypes import wintypes

		kernel = ctypes.WinDLL("kernel32", use_last_error=True)
		kernel.OpenProcess.restype = wintypes.HANDLE
		kernel.GetExitCodeProcess.argtypes = [
			wintypes.HANDLE,
			ctypes.POINTER(wintypes.DWORD),
		]
		kernel.CloseHandle.argtypes = [wintypes.HANDLE]
		handle = kernel.OpenProcess(0x1000, False, pid)
		if not handle:
			return ctypes.get_last_error() != 87  # Access denied is not proof of death.
		try:
			code = wintypes.DWORD()
			return (
				not kernel.GetExitCodeProcess(handle, ctypes.byref(code))
				or code.value == 259
			)
		finally:
			kernel.CloseHandle(handle)
	try:
		os.kill(pid, 0)
		return True
	except ProcessLookupError:
		return False
	except PermissionError:
		return True


def watch_worker(process, path):
	"""Retain an explicit failure even if Python exits before its first update."""
	process.wait()
	job = read_json(path)
	if job["status"] in {"QUEUED", "RUNNING"}:
		job.update(
			status="FAILED",
			reason=f"Worker exited without completion (exit {process.returncode}); partial outputs retained.",
			finished_at=datetime.now(UTC).isoformat(),
		)
		save_job(path, job)


def job_arguments(payload, output, data_root):
	"""Allow only free, typed operations. User text is never executable shell code."""
	if not isinstance(payload, dict) or set(payload) - {
		"action",
		"tickers",
		"ticker",
		"screen",
		"assumptions",
	}:
		raise ValueError("Unknown workbench request fields")
	if payload.get("action") == "screen":
		tickers = payload.get("tickers", "")
		if not isinstance(tickers, str):
			raise ValueError("Tickers must be comma-separated text")
		names = list(dict.fromkeys(symbol(t) for t in tickers.split(",") if t.strip()))
		if len(names) > 30:
			raise ValueError(
				"Use up to 30 watchlist tickers, or leave blank for the US universe"
			)
		return ["run", "--tickers", ",".join(names), "--output-dir", str(output)]
	if payload.get("action") != "deep":
		raise ValueError(
			"Workbench supports free screening and free company analysis only"
		)
	ticker = symbol(payload.get("ticker", ""))
	screen = within_data(data_root / payload.get("screen", ""), data_root)
	if not (screen / "report.json").is_file():
		raise ValueError("Choose a saved screen first")
	return ["deep", str(screen), ticker, "--output-dir", str(output)]


def start_job(payload, data_root):
	# The HTTP handler holds a lock across this function. Only one job is admitted;
	# separate output folders and the CLI's immutable writes protect prior work.
	if any(j["status"] in {"QUEUED", "RUNNING"} for j in jobs(data_root)):
		raise ValueError("A free run is already active; inspect its progress first")
	identifier = (
		datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
	)
	output = data_root / "workspace/runs" / identifier
	arguments = job_arguments(payload, output, data_root)
	if payload.get("assumptions") is not None:
		from smrik_fund.company_model import validate_controls

		assumptions = payload["assumptions"]
		if (
			payload["action"] != "deep"
			or not isinstance(assumptions, dict)
			or set(assumptions) != {"controls", "rationale", "limitations"}
		):
			raise ValueError(
				"Custom assumptions require a deep run and controls/rationale/limitations"
			)
		validate_controls(assumptions["controls"])
		if (
			not isinstance(assumptions["rationale"], str)
			or not assumptions["rationale"].strip()
			or not isinstance(assumptions["limitations"], list)
			or any(not isinstance(s, str) for s in assumptions["limitations"])
		):
			raise ValueError("Explain the assumptions and supply a list of limitations")
		assumption_file = data_root / "workspace/jobs" / f"{identifier}.assumptions.txt"
		assumption_file.parent.mkdir(parents=True, exist_ok=True)
		assumption_file.write_text(json.dumps(assumptions), encoding="utf-8")
		arguments += ["--assumptions", str(assumption_file)]
	path = data_root / "workspace/jobs" / f"{identifier}.json"
	job = {
		"id": identifier,
		"status": "QUEUED",
		"action": payload["action"],
		"ticker": payload.get("ticker"),
		"created_at": datetime.now(UTC).isoformat(),
		"output": output.relative_to(data_root).as_posix(),
		"arguments": arguments,
		"paid_calls": 0,
	}
	save_job(path, job)
	try:
		with path.with_suffix(".log").open("w", encoding="utf-8") as log:
			process = subprocess.Popen(
				[sys.executable, "-m", "smrik_fund.research_workspace", str(path)],
				cwd=ROOT,
				stdout=log,
				stderr=log,
				creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
			)
		threading.Thread(target=watch_worker, args=(process, path), daemon=True).start()
	except OSError as exc:
		job.update(status="FAILED", reason=str(exc))
		save_job(path, job)
		raise
	return job


def execute_job(path):
	"""Runs independently of the web server; completion survives a browser restart."""
	from smrik_fund.daily_cli import app

	job = read_json(path)
	job.update(
		status="RUNNING", started_at=datetime.now(UTC).isoformat(), pid=os.getpid()
	)
	save_job(path, job)
	try:
		app(args=job["arguments"], prog_name="smrik-fund daily", standalone_mode=False)
		out = Path(job["arguments"][job["arguments"].index("--output-dir") + 1])
		outcome = read_json(
			out / ("report.json" if job["action"] == "screen" else "deep-result.json")
		)
		job.update(status="COMPLETED", outcome=outcome["status"])
	except BaseException as exc:
		job.update(status="FAILED", reason=f"{type(exc).__name__}: {exc}")
	finally:
		job["finished_at"] = datetime.now(UTC).isoformat()
		save_job(path, job)


def make_server(data_root=DATA_ROOT, port=8787):
	"""Bind localhost only. Origin/Host and session-token checks protect POSTs."""
	data_root = Path(data_root).resolve()
	token = secrets.token_urlsafe(32)
	admission = threading.Lock()

	class Handler(BaseHTTPRequestHandler):
		def log_message(self, format, *args):
			return  # Job receipts contain useful logs; HTTP polling is just noise.

		def respond(self, status, body, content_type="application/json", extra=None):
			if not isinstance(body, bytes):
				body = json.dumps(body).encode()
			self.send_response(status)
			self.send_header("Content-Type", content_type)
			self.send_header("Content-Length", str(len(body)))
			self.send_header("Cache-Control", "no-store")
			self.send_header("X-Content-Type-Options", "nosniff")
			self.send_header("Referrer-Policy", "no-referrer")
			for name, value in (extra or {}).items():
				self.send_header(name, value)
			self.end_headers()
			self.wfile.write(body)

		def local_request(self):
			port = self.server.server_port
			hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
			return self.headers.get("Host") in hosts and self.headers.get(
				"Origin", f"http://{self.headers.get('Host')}"
			) in {f"http://{h}" for h in hosts}

		def do_GET(self):
			if not self.local_request():
				return self.respond(403, {"error": "Local origin required"})
			path = unquote(urlsplit(self.path).path)
			try:
				if path == "/tokens.css":
					return self.respond(
						200,
						(ROOT / "tokens.css").read_bytes(),
						"text/css; charset=utf-8",
					)
				if path == "/":
					page = PAGE.read_text(encoding="utf-8").replace(
						"__SESSION_TOKEN__", token
					)
					return self.respond(
						200,
						page.encode(),
						"text/html; charset=utf-8",
						{
							"Content-Security-Policy": "default-src 'self'; script-src 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; connect-src 'self'"
						},
					)
				if path == "/api/runs":
					return self.respond(
						200, {"runs": list_runs(data_root), "jobs": jobs(data_root)}
					)
				if path.startswith("/api/audit/"):
					return self.respond(
						200,
						audit_run(
							data_root / path.removeprefix("/api/audit/"), data_root
						),
					)
				if path.startswith("/files/"):
					file = within_data(
						data_root / path.removeprefix("/files/"), data_root
					)
					allowed = (
						file.name in ALLOWED_FILES
						or (file.suffix == ".xlsx" and file.parent.name == "reviewed")
						or (
							file.parent.name == "briefs"
							and file.suffix in {".html", ".md"}
						)
					)
					if not allowed or not file.is_file():
						return self.respond(404, {"error": "Artifact not available"})
					mime = (
						mimetypes.guess_type(file.name)[0] or "application/octet-stream"
					)
					# Historical HTML runs may contain scripts; isolate them from the
					# workbench origin while preserving their own relative links.
					extra = {
						"Content-Security-Policy": "sandbox allow-scripts allow-downloads; default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'"
					}
					if file.suffix == ".xlsx":
						extra["Content-Disposition"] = (
							f'attachment; filename="{file.name}"'
						)
					return self.respond(200, file.read_bytes(), mime, extra)
				return self.respond(404, {"error": "Unknown route"})
			except (ValueError, OSError, KeyError, TypeError) as exc:
				return self.respond(400, {"error": str(exc)})

		def do_POST(self):
			if (
				not self.local_request()
				or self.headers.get("X-Workbench-Token") != token
			):
				return self.respond(403, {"error": "Local session token required"})
			if self.path != "/api/jobs":
				return self.respond(404, {"error": "Unknown route"})
			try:
				length = int(self.headers.get("Content-Length", "0"))
				if not 0 < length <= 20000:
					raise ValueError("Request must be between 1 and 20000 bytes")
				payload = json.loads(self.rfile.read(length))
				with admission:
					job = start_job(payload, data_root)
				return self.respond(202, job)
			except (ValueError, OSError, KeyError, TypeError) as exc:
				return self.respond(400, {"error": str(exc)})

	return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(port=8787):
	server = make_server(port=port)
	print(f"Research workbench: http://127.0.0.1:{server.server_port}", flush=True)
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		pass
	finally:
		server.server_close()


if __name__ == "__main__":
	execute_job(Path(sys.argv[1]))

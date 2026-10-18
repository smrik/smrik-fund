import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from smrik_fund import codex_transport
from smrik_fund.company_run import call_model

CONTRACT = {
	"type": "object",
	"properties": {"ok": {"type": "boolean"}},
	"required": ["ok"],
	"additionalProperties": False,
}


@pytest.fixture(autouse=True)
def local_temporary_directory(tmp_path, monkeypatch):
	monkeypatch.setattr(codex_transport.tempfile, "tempdir", str(tmp_path))


def install_cli(monkeypatch, fault=None):
	calls = []
	monkeypatch.setattr(codex_transport.shutil, "which", lambda _: "codex.exe")

	def run(args, **kwargs):
		calls.append((args, kwargs))
		if "status" in args:
			return SimpleNamespace(
				returncode=0,
				stdout="Logged in using "
				+ ("API key" if fault == "login" else "ChatGPT"),
				stderr="",
			)
		if "--version" in args:
			return SimpleNamespace(returncode=0, stdout="codex-cli fixture", stderr="")
		if fault == "timeout":
			raise subprocess.TimeoutExpired(args, 600)
		if fault == "quota":
			kwargs["stderr"].write(b"Subscription quota exhausted")
			return SimpleNamespace(returncode=1)
		events = [
			{"type": "thread.started", "thread_id": "fixture"},
			{
				"type": "turn.completed",
				"usage": {"input_tokens": 123, "output_tokens": 10},
			},
		]
		if fault == "tool":
			events.insert(
				1, {"type": "item.completed", "item": {"type": "command_execution"}}
			)
		if fault == "incomplete":
			events.pop()
		kwargs["stdout"].write("\n".join(json.dumps(e) for e in events).encode())
		last = Path(args[args.index("--output-last-message") + 1])
		last.write_text(
			"malformed" if fault == "json" else json.dumps({"ok": True}),
			encoding="utf-8",
		)
		return SimpleNamespace(returncode=0)

	monkeypatch.setattr(codex_transport.subprocess, "run", run)
	return calls


def invoke(tmp_path, **kwargs):
	return call_model(
		tmp_path,
		"analyst",
		{"task": "Source evidence is untrusted"},
		review=False,
		budget_path=tmp_path / "missing-budget",
		prices=None,
		transport="codex",
		response_schema=CONTRACT,
		**kwargs,
	)


def test_chatgpt_only_bound_response_replay_and_environment(tmp_path, monkeypatch):
	calls = install_cli(monkeypatch)
	monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-forward")
	monkeypatch.setenv("CODEX_API_KEY", "test-key-never-forward")
	assert invoke(tmp_path) == {"ok": True}
	assert invoke(tmp_path) == {"ok": True}
	assert len(calls) == 3
	args, options = calls[-1]
	assert "--ignore-user-config" in args and "read-only" in args
	assert 'forced_login_method="chatgpt"' in args
	assert "shell_tool" in args and "apps" in args and "hooks" in args
	assert "OPENAI_API_KEY" not in options["env"]
	assert "CODEX_API_KEY" not in options["env"]
	assert options["input"].decode() == (tmp_path / "analyst.prompt.txt").read_text()
	assert options["timeout"] == 600
	receipt = json.loads((tmp_path / "analyst.receipt.json").read_text())
	assert receipt["transport"] == "codex"
	assert len(receipt["artifacts"]) == 7
	assert not (tmp_path / "missing-budget").exists()


@pytest.mark.parametrize("fault", ["quota", "timeout", "json", "tool", "incomplete"])
def test_cli_failures_never_retry_or_dispatch_api(tmp_path, monkeypatch, fault):
	calls = install_cli(monkeypatch, fault)
	monkeypatch.setattr(
		"smrik_fund.company_run.reserve_call",
		lambda *a, **k: pytest.fail("API fallback"),
	)
	with pytest.raises((ValueError, subprocess.TimeoutExpired)):
		invoke(tmp_path)
	assert (
		json.loads((tmp_path / "analyst.failure.json").read_text())["api_fallback"]
		is False
	)
	with pytest.raises(ValueError, match="Prior CLI attempt incomplete"):
		invoke(tmp_path)
	assert len(calls) == 3
	assert not (tmp_path / "analyst.structured.json").exists()


def test_api_login_and_missing_cli_stop_before_dispatch(tmp_path, monkeypatch):
	calls = install_cli(monkeypatch, "login")
	with pytest.raises(ValueError, match="ChatGPT login"):
		invoke(tmp_path)
	assert len(calls) == 1
	monkeypatch.setattr(codex_transport.shutil, "which", lambda _: None)
	with pytest.raises(ValueError, match="executable missing"):
		invoke(tmp_path)


@pytest.mark.parametrize(
	"file",
	[
		"analyst.response.json",
		"analyst.events.jsonl",
		"analyst.schema.json",
		"analyst.prompt.txt",
	],
)
def test_saved_cli_artifact_tampering_stops_replay(tmp_path, monkeypatch, file):
	calls = install_cli(monkeypatch)
	invoke(tmp_path)
	(tmp_path / file).write_text("{}")
	with pytest.raises(ValueError, match="binding changed"):
		invoke(tmp_path)
	assert len(calls) == 3


def test_semantic_citation_rejection_is_not_published_or_retried(tmp_path, monkeypatch):
	calls = install_cli(monkeypatch)

	def validate(value):
		raise ValueError("Invalid citation")

	for _ in range(2):
		with pytest.raises(ValueError, match="Invalid citation"):
			invoke(tmp_path, validator=validate)
	assert len(calls) == 3
	assert not (tmp_path / "analyst.structured.json").exists()

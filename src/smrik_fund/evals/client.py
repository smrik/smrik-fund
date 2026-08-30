"""A counting, recording proxy around the OpenAI client.

The product accepts an injected ``client`` on every model-calling entry point,
so the harness can observe execution without touching product code.  This proxy
gives us three contract requirements for free:

* **call accounting** - exact per-stage product call counts;
* **rejected-output preservation** - the raw structured output is captured here
  *before* the product's validators run, so a VALIDATION_REJECTED case still has
  a diagnosable payload without a product-side diagnostic hook;
* **budget enforcement** - an optional hard ceiling on live calls.

Nothing recorded here is canonical product state.  The runner marks it
UNTRUSTED and never feeds it to the judge.
"""

from __future__ import annotations

from typing import Any


class CallBudgetExceeded(RuntimeError):
	"""Raised when a run would exceed its configured live-call ceiling."""


class RecordingClient:
	"""Wrap an OpenAI client, counting calls and capturing raw output."""

	def __init__(self, inner: Any, *, max_calls: int | None = None) -> None:
		self._inner = inner
		self._max_calls = max_calls
		self.calls: list[dict[str, Any]] = []
		self.responses = _Responses(self)

	@property
	def call_count(self) -> int:
		return len(self.calls)

	def stage_counts(self) -> dict[str, int]:
		"""Return per-stage call counts, keyed by the parsed output type."""
		counts: dict[str, int] = {}
		for call in self.calls:
			stage = call["stage"]
			counts[stage] = counts.get(stage, 0) + 1
		return counts

	def raw_outputs(self) -> list[dict[str, Any]]:
		"""Return every captured structured output, newest last."""
		return [
			{
				"stage": call["stage"],
				"model": call["model"],
				"reasoning_effort": call["reasoning_effort"],
				"output": call["output"],
			}
			for call in self.calls
		]

	def _record(self, kwargs: dict[str, Any], response: Any) -> None:
		text_format = kwargs.get("text_format")
		stage = getattr(text_format, "__name__", "unknown")
		parsed = getattr(response, "output_parsed", None)
		output: Any = None
		if parsed is not None:
			try:
				output = parsed.model_dump(mode="json")
			except AttributeError:
				output = repr(parsed)
		usage = getattr(response, "usage", None)
		self.calls.append(
			{
				"stage": stage,
				"model": kwargs.get("model"),
				"reasoning_effort": (kwargs.get("reasoning") or {}).get("effort"),
				"output": output,
				"usage": _usage(usage),
			}
		)

	def _check_budget(self) -> None:
		if self._max_calls is not None and len(self.calls) >= self._max_calls:
			raise CallBudgetExceeded(
				f"live call budget of {self._max_calls} is exhausted"
			)


def _usage(usage: Any) -> dict[str, Any] | None:
	"""Retain SDK usage metadata when it is offered, without inventing it."""
	if usage is None:
		return None
	try:
		return usage.model_dump(mode="json")
	except AttributeError:
		return None


class _Responses:
	def __init__(self, owner: RecordingClient) -> None:
		self._owner = owner

	def parse(self, **kwargs: Any) -> Any:
		self._owner._check_budget()
		response = self._owner._inner.responses.parse(**kwargs)
		self._owner._record(kwargs, response)
		return response

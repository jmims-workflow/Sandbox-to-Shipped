"""A stand-in for the Claude client, for tests and the recorded walkthrough.

It returns canned structured answers and never opens a network connection. The app uses it
only when STS_FAKE_CLAUDE is set in live mode with no real key (see sts/config.py). It is a
development tool: nothing in the app's pages mentions it.
"""

from __future__ import annotations

from types import SimpleNamespace

from .provider import DraftReason, MatchResult, SizeUp


class FakeMessages:
    """Stands in for client.beta.messages. Returns canned structured output."""

    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        shape = kwargs["output_format"]
        value = self.outputs[shape.__name__]
        parsed = value(kwargs) if callable(value) else value
        return SimpleNamespace(stop_reason="end_turn", parsed_output=parsed)


def fake_client(outputs=None):
    """A client shaped like anthropic.Anthropic, and its FakeMessages so callers can see the calls."""
    msgs = FakeMessages(outputs if outputs is not None else dict(DEFAULT_OUTPUTS))
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs)), msgs


DEFAULT_OUTPUTS = {
    "MatchResult": MatchResult.model_validate(
        {"matches": [{"tool_id": "call-recap-writer", "confidence": "close", "reason": "It writes follow-up emails."}]}
    ),
    "SizeUp": SizeUp.model_validate(
        {
            "title": "Short follow-up emails",
            "bullets": [{"label": "Closest match", "text": "Call Recap Writer."}, {"label": "Worth asking", "text": "How often?"}],
            "security_check_needed": False,
        }
    ),
    "DraftReason": DraftReason(reason="Drafted reason text.", what_would_change="Drafted change text."),
}

from sts.demo_data import load_demo_data
from sts.matching import clean_matches, eligible_tools, word_overlap_matches
from sts.provider import ClaudeProvider, MatchResult

from .conftest import DEMO_DIR, fake_client


def inventory():
    return load_demo_data(DEMO_DIR).tools


def test_clean_matches_drops_unknown_and_retired_ids():
    raw = [
        {"tool_id": "made-up-tool", "confidence": "close", "reason": "x"},
        {"tool_id": "subject-line-tester", "confidence": "close", "reason": "retired"},
        {"tool_id": "call-recap-writer", "confidence": "close", "reason": "fits"},
    ]
    assert [m["tool_id"] for m in clean_matches(raw, inventory())] == ["call-recap-writer"]


def test_clean_matches_keeps_at_most_two_and_no_duplicates_or_bad_confidence():
    raw = [
        {"tool_id": "call-recap-writer", "confidence": "close", "reason": "a"},
        {"tool_id": "call-recap-writer", "confidence": "possible", "reason": "dupe"},
        {"tool_id": "proposal-drafter", "confidence": "certain", "reason": "bad confidence"},
        {"tool_id": "case-study-builder", "confidence": "possible", "reason": "b"},
        {"tool_id": "webinar-invite-writer", "confidence": "possible", "reason": "c"},
    ]
    out = clean_matches(raw, inventory())
    assert [m["tool_id"] for m in out] == ["call-recap-writer", "case-study-builder"]


def test_eligible_tools_never_include_retired():
    assert all(t.status != "retired" for t in eligible_tools(inventory()))


def test_word_overlap_finds_webinar_tool():
    out = word_overlap_matches("Write invite and reminder emails for our webinar from the event brief", inventory())
    assert out[0]["tool_id"] == "webinar-invite-writer"
    assert out[0]["confidence"] == "close"
    assert "webinar" in out[0]["reason"]


def test_word_overlap_never_returns_retired_tools():
    out = word_overlap_matches("Suggest email subject lines for marketing sends", inventory())
    assert "subject-line-tester" not in [m["tool_id"] for m in out]


def test_word_overlap_with_no_shared_words_returns_nothing():
    assert word_overlap_matches("Plan the office holiday party menu", inventory()) == []


def test_claude_matches_are_validated_against_inventory():
    bogus = MatchResult.model_validate(
        {
            "matches": [
                {"tool_id": "invented-tool", "confidence": "close", "reason": "x"},
                {"tool_id": "subject-line-tester", "confidence": "possible", "reason": "y"},
            ]
        }
    )
    client, msgs = fake_client({"MatchResult": bogus})
    provider = ClaudeProvider("k", "claude-sonnet-5-5", client=client)
    result = provider.find_matches("subject lines", ["public_only"], inventory())
    assert result.matches == []
    # Retired tools are never even offered to Claude.
    sent = msgs.calls[0]["messages"][0]["content"]
    assert "subject-line-tester" not in sent
    assert "<request_data>" in sent

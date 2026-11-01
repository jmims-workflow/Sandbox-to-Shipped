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


# ---- Asked before ---------------------------------------------------------------

from sts.matching import clean_related, word_overlap_related  # noqa: E402
from sts.provider import DemoProvider  # noqa: E402

PAST = [
    {"id": "r-1044", "title": "Reply to inbound demo requests automatically",
     "task": "When someone fills in the demo request form, reply right away.", "outcome": "not_approved",
     "reason": "It would send emails on its own.", "what_would_change": "A drafted version."},
    {"id": "r-1042", "title": "Translate help center articles", "task": "Translate help center articles.",
     "outcome": "use_existing", "reason": "Translation Helper does this.", "what_would_change": "A glossary."},
]


def test_clean_related_drops_ids_that_were_not_sent():
    assert clean_related({"request_id": "r-9999", "reason": "x"}, PAST) is None
    assert clean_related({"request_id": "", "reason": "x"}, PAST) is None
    assert clean_related(None, PAST) is None
    assert clean_related("r-1044", PAST) is None
    assert clean_related({"request_id": "r-1044", "reason": "Same idea."}, PAST) == {
        "request_id": "r-1044", "reason": "Same idea."}
    # An id that exists in the data but was not in the list sent is dropped too.
    assert clean_related({"request_id": "r-1044", "reason": "x"}, PAST[1:]) is None


def test_claude_related_decision_is_validated_and_names_never_sent():
    data = load_demo_data(DEMO_DIR)
    requests = {r.id: r for r in data.requests}
    past = [{"id": d.request_id, "title": requests[d.request_id].title, "task": requests[d.request_id].task,
             "outcome": d.outcome, "reason": d.reason, "what_would_change": d.what_would_change}
            for d in data.decisions]
    bogus = MatchResult.model_validate({"matches": [], "related_decision": {"request_id": "r-0001", "reason": "x"}})
    client, msgs = fake_client({"MatchResult": bogus})
    provider = ClaudeProvider("k", "claude-sonnet-5-5", client=client)
    result = provider.find_matches("auto-reply to demo requests", [], data.tools, past)
    assert result.related is None
    sent = msgs.calls[0]["messages"][0]["content"]
    assert "Past decisions" in sent and "r-1044" in sent
    for r in data.requests:
        assert r.requester_name not in sent
    for d in data.decisions:
        assert d.decided_by not in sent

    good = MatchResult.model_validate({"matches": [], "related_decision": {"request_id": "r-1044", "reason": "Same."}})
    client, _ = fake_client({"MatchResult": good})
    provider = ClaudeProvider("k", "claude-sonnet-5-5", client=client)
    assert provider.find_matches("auto-reply", [], data.tools, past).related == {"request_id": "r-1044",
                                                                                 "reason": "Same."}


def test_demo_word_match_finds_the_auto_reply_decision():
    related = word_overlap_related("auto-reply to demo requests", PAST)
    assert related["request_id"] == "r-1044"
    assert word_overlap_related("Plan the office holiday party menu", PAST) is None


def test_demo_provider_prefilled_example_has_no_related_decision():
    data = load_demo_data(DEMO_DIR)
    provider = DemoProvider(data.recorded, data.requests)
    example = next(r for r in data.requests if r.id == data.example_request_id)
    out = provider.find_matches(example.task, example.info, data.tools, PAST)
    assert out.source == "recorded" and out.related is None
    out = provider.find_matches("auto-reply to demo requests", [], data.tools, PAST)
    assert out.source == "word" and out.related["request_id"] == "r-1044"

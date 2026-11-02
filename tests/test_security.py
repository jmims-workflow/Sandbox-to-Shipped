"""The automatic security check, set by security: rules file, every path and the early warnings."""

import shutil

import pytest

from sts.config import ROOT
from sts.security import (
    QUESTIONS,
    RESULTS,
    WARN_SENDS,
    WARN_SENSITIVE,
    SecurityRulesError,
    answer_errors,
    check_security,
    check_security_rules,
    early_warnings,
    load_security_rules,
)

RULES = load_security_rules(ROOT / "security_rules.yaml")
ALL_NO = {"sends_without_check": "no", "keeps_elsewhere": "no", "ai_service": "claude"}


def test_northstar_rules_file():
    assert RULES.service_names == {"claude": "Claude (by Anthropic)",
                                   "meridian": "Meridian Assist (Northstar's private instance)"}
    assert RULES.information == {"customer_contact": "automatic", "deal_pricing": "automatic",
                                 "internal_notes": "automatic", "sensitive_personal": "person", "public_only": "none"}
    assert list(RULES.service_choices())[-2:] == ["something_else", "not_sure"]


# ---- Every path through the check ----------------------------------------------------


def test_only_public_information_needs_no_check():
    result = check_security(["public_only"], {}, RULES)
    assert result.result == "not_needed" and result.reasons == []
    assert result.text == "Security screening: not needed"


@pytest.mark.parametrize("answers", [ALL_NO, {}, {"sends_without_check": "yes", "keeps_elsewhere": "yes",
                                                  "ai_service": "something_else"}])
def test_sensitive_personal_always_goes_to_a_person_whatever_the_answers(answers):
    result = check_security(["sensitive_personal", "public_only"], answers, RULES)
    assert result.result == "person"
    assert result.text == "Security screening: a person from security will review this"
    assert "sensitive personal information" in result.reasons[0]


@pytest.mark.parametrize("kind", ["internal_notes", "customer_contact", "deal_pricing"])
@pytest.mark.parametrize("service", ["claude", "meridian"])
def test_all_no_with_an_approved_service_passes_automatically(kind, service):
    result = check_security([kind, "public_only"], {**ALL_NO, "ai_service": service}, RULES)
    assert result.result == "passed" and result.reasons == []
    assert result.text == "Security screening: passed automatically against security's rules"


@pytest.mark.parametrize("question", ["sends_without_check", "keeps_elsewhere"])
@pytest.mark.parametrize("value,said", [("yes", "Yes"), ("not_sure", "Not sure")])
def test_each_yes_or_not_sure_goes_to_a_person_and_names_the_answer(question, value, said):
    result = check_security(["customer_contact"], {**ALL_NO, question: value}, RULES)
    assert result.result == "person"
    assert result.reasons == [f"“{QUESTIONS[question]}” was answered {said}."]


@pytest.mark.parametrize("service,said", [("not_sure", "Not sure"), ("something_else", "Something else")])
def test_unsure_or_other_service_goes_to_a_person_and_names_the_answer(service, said):
    result = check_security(["internal_notes"], {**ALL_NO, "ai_service": service}, RULES)
    assert result.result == "person"
    assert result.reasons == [f"“Which AI service would it use?” was answered {said}."]


def test_unapproved_service_goes_to_a_person():
    result = check_security(["deal_pricing"], {**ALL_NO, "ai_service": "some-other-ai"}, RULES)
    assert result.result == "person"
    assert "isn't on security's approved list" in result.reasons[0]


def test_every_answer_that_sent_it_to_a_person_is_named():
    answers = {"sends_without_check": "yes", "keeps_elsewhere": "not_sure", "ai_service": "not_sure"}
    result = check_security(["customer_contact"], answers, RULES)
    assert len(result.reasons) == 3
    assert "was answered Yes" in result.reasons[0] and "was answered Not sure" in result.reasons[1]


def test_missing_answers_go_to_a_person():
    result = check_security(["customer_contact"], {}, RULES)
    assert result.result == "person" and all("wasn't answered" in r for r in result.reasons)


def test_result_text_covers_all_three_results():
    assert set(RESULTS) == {"not_needed", "passed", "person"}


def test_questions_are_required_only_beyond_public_information():
    assert answer_errors(["public_only"], {}, RULES) == {}
    assert set(answer_errors(["internal_notes"], {}, RULES)) == {"sends_without_check", "keeps_elsewhere",
                                                                 "ai_service"}
    assert answer_errors(["internal_notes"], ALL_NO, RULES) == {}


# ---- Early warnings: rules in code, never a score -----------------------------------------


def test_early_warnings():
    assert early_warnings(["public_only"], {}) == {}
    assert early_warnings(["customer_contact"], {"sends_without_check": "yes"}) == {"sends_without_check": WARN_SENDS}
    assert early_warnings(["sensitive_personal"], {}) == {"info": WARN_SENSITIVE}
    assert WARN_SENDS == ("Heads up: Northstar doesn't approve tools that send to customers on their own. A version "
                          "that drafts for a person to check and send is much more likely to be approved.")
    assert WARN_SENSITIVE == ("Requests with sensitive personal information always get a review from security, so "
                              "expect this one to take longer.")
    for text in (WARN_SENDS, WARN_SENSITIVE):
        assert "%" not in text and "score" not in text.lower() and "chance" not in text.lower()


# ---- The rules file is checked at startup with helpful errors ----------------------------


def write_rules(tmp_path, text):
    path = tmp_path / "security_rules.yaml"
    path.write_text(text)
    return path


def good_text():
    return (ROOT / "security_rules.yaml").read_text()


def test_bad_level_is_explained(tmp_path):
    path = write_rules(tmp_path, good_text().replace("deal_pricing: automatic", "deal_pricing: sometimes"))
    assert check_security_rules(path) == ["security_rules.yaml, information.deal_pricing: use none, automatic or person"]


def test_missing_information_kind_is_explained(tmp_path):
    path = write_rules(tmp_path, good_text().replace("  sensitive_personal: person\n", ""))
    problems = check_security_rules(path)
    assert len(problems) == 1 and "information" in problems[0] and "sensitive_personal" in problems[0]


def test_unknown_information_kind_is_explained(tmp_path):
    path = write_rules(tmp_path, good_text() + "  health: person\n")
    problems = check_security_rules(path)
    assert "health is not an information kind" in problems[0]


def test_no_services_and_typos_are_explained(tmp_path):
    text = good_text()
    start, end = text.index("approved_services:"), text.index("# For each kind")
    path = write_rules(tmp_path, text[:start] + "approved_services: []\n\n" + text[end:] + "extra_setting: 1\n")
    problems = check_security_rules(path)
    assert "security_rules.yaml, approved_services: list at least one approved AI service" in problems
    assert any(p.startswith("security_rules.yaml, extra_setting: not a setting") for p in problems)


def test_reserved_and_duplicate_service_ids(tmp_path):
    path = write_rules(tmp_path, good_text().replace("id: meridian", "id: not_sure"))
    assert "kept for the form's own choices" in check_security_rules(path)[0]
    path = write_rules(tmp_path, good_text().replace("id: meridian", "id: claude"))
    assert "two services share the same id" in check_security_rules(path)[0]


def test_broken_or_missing_file(tmp_path):
    assert "not valid YAML" in check_security_rules(write_rules(tmp_path, "information: [unclosed"))[0]
    assert "file not found" in check_security_rules(tmp_path / "nope.yaml")[0]


def test_app_refuses_to_start_with_bad_rules(tmp_path):
    from sts.config import Settings
    from sts.web import create_app

    path = write_rules(tmp_path, good_text().replace("public_only: none", "public_only: maybe"))
    with pytest.raises(SecurityRulesError) as exc:
        create_app(Settings(requested_mode="demo", demo_dir=ROOT / "demo", security_rules_path=path))
    assert "information.public_only" in str(exc.value)


def test_check_data_reports_rules_problems(tmp_path):
    from sts.demo_data import check_demo_data

    demo = tmp_path / "demo"
    shutil.copytree(ROOT / "demo", demo)
    path = write_rules(tmp_path, good_text().replace("internal_notes: automatic", "internal_notes: x"))
    assert check_demo_data(demo, path) == ["security_rules.yaml, information.internal_notes: use none, automatic or person"]


# ---- Demo data -------------------------------------------------------------------------------


def test_demo_requests_show_each_result():
    from sts.demo_data import load_demo_data

    reqs = {r.id: r for r in load_demo_data(ROOT / "demo").requests}
    assert reqs["r-1047"].title == "Social posts from case studies"
    assert reqs["r-1047"].security_result == {"result": "passed", "reasons": []}
    assert reqs["r-1046"].security_result["result"] == "person"
    assert reqs["r-1046"].security_result["reasons"] == ["“Which AI service would it use?” was answered Not sure."]
    benefits = reqs["r-1049"]
    assert benefits.title == "Answer employee benefits questions" and benefits.team == "People"
    assert benefits.status == "waiting" and "sensitive_personal" in benefits.info
    assert benefits.security_result["result"] == "person"

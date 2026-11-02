"""The README carries the design principle on room and the Why standards paragraph."""

from sts.config import ROOT

WHY = ('Why standards. Every "no" in this app points to something written down: security\'s rules, the review '
       "checklist, the number of pilot slots, or a past decision. The idea, borrowed from Stuart Diamond's Getting "
       "More, is that a decision should rest on an agreed standard, so the conversation is about the standard and "
       "not about anyone's feelings. It also means no single reviewer has to be the bad guy.")
ROOM = ("**Room is part of the standard.** Only a set number of tools can be in pilot at once. When the pilots are "
        "full, a new yes means shipping or retiring something first, or a Not now with a date to look again. The "
        "limit is shown openly, so a capacity decision is about the limit, not the person asking.")


def readme():
    return (ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_has_the_why_standards_paragraph_after_the_principles():
    text = readme()
    assert WHY in text
    principles = text.index("## Design choices and why")
    assert principles < text.index(WHY) < text.index("## What you can try in the demo")
    # Directly after the last principle.
    assert text[:text.index(WHY)].rstrip().endswith("a decision history people can search.")


def test_room_principle_follows_shipped_and_the_rest_are_renumbered():
    text = readme()
    assert f"10. **Shipped means it earned it.**" in text
    assert f"11. {ROOM}" in text
    assert "12. **Demo mode uses the real logic.**" in text and "13. **Honest about the alternative.**" in text
    assert "A Not now always comes with a date to look again." in text


def test_how_it_works_page_has_the_paragraph(demo_client):
    html = demo_client.get("/how-it-works").text.replace("&#34;", '"').replace("&#39;", "'")
    assert WHY in html
    assert "Room is part of the standard." in html and "Pilot slots" in html and "Not now" in html

"""The README and docs: required sections word for word, working links, and a README short enough to read."""

import re

import pytest

from sts.config import ROOT

WHY = ('Why standards. Every "no" in this app points to something written down: security\'s rules, the review '
       "checklist, the number of pilot slots, or a past decision. The idea, borrowed from Stuart Diamond's Getting "
       "More, is that a decision should rest on an agreed standard, so the conversation is about the standard and "
       "not about anyone's feelings. It also means no single reviewer has to be the bad guy.")
ROOM = ("**Room is part of the standard.** Only a set number of tools can be in pilot at once. When the pilots are "
        "full, a new yes means shipping or retiring something first, or a Not now with a date to look again. The "
        "limit is shown openly, so a capacity decision is about the limit, not the person asking.")

OPENING = ("Sandbox to Shipped helps teams turn scattered AI requests into accountable decisions: checking existing "
           "tools first, screening for security, and moving pilots toward approval or retirement. AI assists with "
           "discovery and explanations. People make decisions. Code enforces the gates.")

MY_ROLE = """
My role
I created Sandbox to Shipped to address a problem I've encountered in my own work: teams need better ways to evaluate AI tool requests, avoid building what already exists, and make consistent decisions about what gets approved.
I led the product design and directed the build, using Claude for planning and Claude Code for implementation.
The decisions I owned
Problem and scope: I evaluated potential AI applications against real organizational needs and chose to focus on the process of requesting, reviewing, and approving AI tools. Checking what's already available comes from my own experience helping teams adopt new workflows.
Human oversight: AI can identify possible matches, assess requests, and draft explanations. People make the decisions, and application rules enforce the required checks.
Fair and consistent decisions: I designed the review process around documented standards, security requirements, pilot capacity, and clear explanations. A request that isn't approved should still have a useful next step.
Practical adoption: I chose to ask employees questions they can reasonably answer rather than requiring speculative time-savings estimates. I also designed privacy, ownership consent, and uncertainty into the app.
User experience: I directed the navigation, visual design, and language to make the application approachable for people who don't have technical backgrounds.
How I worked with AI
I used Claude as a planning and critical-thinking partner to challenge assumptions, explore alternatives, develop screen concepts, and translate my decisions into detailed specifications. Claude Code wrote the application code and automated tests.
I also sought independent reviews, evaluated the recommendations, and incorporated changes that materially improved the application.
How I tested and refined it
I reviewed change summaries and test results before merging updates, then tested the deployed application myself.
That hands-on testing caught usability problems that automated checks didn't, including a prefilled form that made the example confusing and a confirmation page that didn't clearly explain what happened next. I used those findings to direct further revisions.
I also configured the Google Cloud Run deployment, including API key storage through Secret Manager and spending controls.
What I deliberately left out
I kept the public demo focused on demonstrating the application's decision process without requiring accounts or storing visitor submissions.
Real authentication and role-based access, persistent hosted storage, and durable usage limits would be necessary for a multi-user production deployment. I've documented those requirements in the production roadmap.
What this project demonstrates
My strength is identifying workflow problems, designing practical AI-supported solutions, and guiding them from concept through implementation and testing. I bring business process knowledge, product judgment, and hands-on experience directing AI-assisted development, rather than a traditional software engineering background.
"""

PART_OF_A_SET = """
Part of a set
Sandbox to Shipped is one of three apps that follow an AI tool through its life at a company:
Sandbox to Shipped (this repo): should we build or approve this AI tool?
Rollout Ready: does a change to the tool's prompt make it better or worse before the team sees it?
AI Adoption & Impact Tracker: once it's live, are people using it, and is it helping?
They are separate apps with no shared code. Together they cover deciding, testing and measuring.
"""

WALKTHROUGH_NOTE = ("Recorded on a local copy in live mode, with a stand-in for Claude so the run is repeatable. In "
                    "this single-user prototype, the same person switches between requester and reviewer; a real "
                    "deployment would need sign-in and roles (see docs/production.md).")

ORDER = ["## The problem", "## Who it's for", "## Walkthrough", "## What I built", "## My role", "## Design choices",
         "## How it works", "## Testing", "## Limitations and the production path", "## Part of a set",
         "## Quick start"]
DOCS = ["production.md", "deploy.md", "configuration.md", "design.md", "architecture.md", "testing.md"]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def readme():
    return read("README.md")


def plain(markdown: str) -> str:
    """Markdown as plain words: no heading marks, bullets, bold or link targets, spaces normalized."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", markdown)
    text = re.sub(r"(?m)^\s*(#+|[-*])\s+", "", text)
    text = text.replace("**", "")
    return re.sub(r"\s+", " ", text).strip()


def section(text: str, heading: str) -> str:
    start = text.index(heading)
    nxt = text.find("\n## ", start + len(heading))
    return text[start:] if nxt == -1 else text[start:nxt]


def test_readme_opens_with_the_title_and_the_opening_word_for_word():
    text = readme()
    assert "# Sandbox to Shipped\n\n" + OPENING in text
    assert text.index("# Sandbox to Shipped") < text.index("Try it live: https://sandbox-to-shipped-103749504031")
    assert "actions/workflows/tests.yml/badge.svg" in text


def test_readme_sections_are_in_order():
    text = readme()
    positions = [text.index(h + "\n") for h in ORDER]
    assert positions == sorted(positions)


def test_my_role_is_word_for_word():
    assert plain(section(readme(), "## My role")) == plain(MY_ROLE)
    # The headings are formatted as headings.
    for h in ["The decisions I owned", "How I worked with AI", "How I tested and refined it",
              "What I deliberately left out", "What this project demonstrates"]:
        assert f"\n### {h}\n" in readme()


def test_part_of_a_set_is_word_for_word():
    part = section(readme(), "## Part of a set")
    assert plain(part) == plain(PART_OF_A_SET)
    assert "(https://github.com/jmims-workflow/Rollout-Ready)" in part
    assert "(https://github.com/jmims-workflow/ai-adoption-tracker)" in part


def test_walkthrough_note_and_how_to_rerun():
    walk = section(readme(), "## Walkthrough")
    assert plain(WALKTHROUGH_NOTE) in plain(walk)
    assert "docs/walkthrough.gif" in walk and "docs/walkthrough.mp4" in walk
    assert "node scripts/walkthrough.js" in walk
    assert (ROOT / "scripts" / "walkthrough.js").exists()


def test_readme_has_the_why_standards_paragraph_after_the_principles():
    text = readme()
    assert WHY in text
    design = section(text, "## Design choices")
    assert WHY in design and "(docs/design.md)" in design
    assert text[:text.index(WHY)].rstrip().endswith("this app has to earn its place.")


def test_design_doc_keeps_every_principle_and_why_standards():
    text = read("docs/design.md")
    assert WHY in text
    assert "10. **Shipped means it earned it.**" in text
    assert f"11. {ROOM}" in text
    assert "12. **Demo mode uses the real logic.**" in text and "13. **Honest about the alternative.**" in text
    assert "A Not now always comes with a date to look again." in text
    assert text[:text.index(WHY)].rstrip().endswith("a decision history people can search.")


def test_how_it_works_page_has_the_paragraph(demo_client):
    html = demo_client.get("/how-it-works").text.replace("&#34;", '"').replace("&#39;", "'")
    assert WHY in html
    assert "Room is part of the standard." in html and "Pilot slots" in html and "Not now" in html


@pytest.mark.parametrize("name", DOCS)
def test_docs_exist(name):
    assert (ROOT / "docs" / name).is_file()


def test_production_doc_is_marked_not_built_and_covers_each_item():
    text = read("docs/production.md")
    assert "Not built" in text
    for heading in ["Sign-in and roles", "Lasting storage", "Limits that survive restarts", "What Decided before shares",
                    "Notifications", "Measuring the AI", "Keys and cost", "Security screening limits"]:
        assert heading in text
    for part in ["Today:", "Production needs:", "Why:"]:
        assert text.count(part) >= 8


def test_deploy_doc_has_the_cloud_shell_reminder_and_hidden_key_rotation():
    text = read("docs/deploy.md")
    assert "cd Sandbox-to-Shipped && git pull" in text
    assert "read -s" in text and "gcloud secrets versions add anthropic-api-key --data-file=-" in text
    assert "gcloud secrets versions disable" in text
    assert "--max-instances 1" in text


def markdown_files():
    return [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]


def test_every_relative_link_points_to_a_file_that_exists():
    broken = []
    for md in markdown_files():
        text = re.sub(r"(?s)```.*?```", "", md.read_text(encoding="utf-8"))
        targets = re.findall(r"\]\(([^)\s]+)\)", text) + re.findall(r'<img[^>]*\ssrc="([^"]+)"', text)
        for target in targets:
            if re.match(r"(https?:|mailto:|#)", target):
                continue
            path = target.split("#")[0]
            if not (md.parent / path).exists():
                broken.append(f"{md.relative_to(ROOT)}: {target}")
    assert not broken, broken


def test_repo_files_are_linked_relatively():
    # Files in this repo are linked with relative paths, never full web addresses.
    for md in markdown_files():
        text = md.read_text(encoding="utf-8")
        assert not re.search(r"\]\(https?://[^)]*/(docs|blob|tree)/[^)]*\.md\)", text), md
        assert "claude.ai/chat" not in text, md


def readme_prose_words() -> int:
    text = readme()
    for heading in ["## My role", "## Part of a set"]:
        text = text.replace(section(text, heading), "")
    text = re.sub(r"(?s)```.*?```", " ", text)                     # code and the diagram
    text = re.sub(r"(?s)<details>.*?</details>", " ", text)        # the screenshots
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)               # images
    text = re.sub(r"<[^>]+>", " ", text)                           # html tags
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)           # keep link words, drop targets
    return len(re.findall(r"[A-Za-z0-9][\w'&.-]*", text))


def test_readme_prose_reads_in_about_three_minutes():
    assert readme_prose_words() < 1000


def test_decided_before_is_never_called_anonymous():
    for md in [*markdown_files(), ROOT / "CLAUDE.md"]:
        assert "anonymous decision" not in md.read_text(encoding="utf-8").lower(), md
    assert "requester names omitted" in readme().lower()
    assert "requester names omitted" in read("CLAUDE.md").lower()

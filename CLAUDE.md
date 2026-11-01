# CLAUDE.md

Notes for future sessions working on Sandbox to Shipped.

## What this is

Sandbox to Shipped ("One front door for AI tool requests.") is a FastAPI web app where anyone at a company asks for an AI tool, sees whether an approved tool already does the job, and later sees the decision with a plain reason. Reviewers work one queue with a short checklist and a reason Claude drafts for them to edit. Approved tools start as "being tried" and get shipped to approved.

Users: requesters (marketers, sellers, support staff; non-engineers), reviewers (the AI tools lead, plus security for customer data), and tool owners.

## Run and test

```bash
pip install -e ".[dev]"
```

```bash
sts serve
```

```bash
pytest
```

```bash
sts check-data
```

- Demo mode (`STS_MODE=demo`, the default) needs no key, makes no network calls and saves nothing.
- Live mode needs `STS_MODE=live` and `ANTHROPIC_API_KEY`. Data goes to `DATA_DIR/sts.db`. `sts seed --reset` loads the demo data.
- Screenshots: start the app in demo mode, then `node scripts/screenshots.js`.

## Layout

- `sts/provider.py`: every Claude call. Keep all Claude calls here.
- `sts/rules.py`: checklist and decision rules. `sts/matching.py`: match validation and the demo word match.
- `sts/store.py`: DemoStore (read only) and LiveStore (SQLite). `sts/web.py`: routes. `templates/`, `static/`.
- `demo/`: `tools.yaml`, `requests.yaml`, `recorded/<request-id>.json`. Every demo date is stored as an offset from today ("today", "3 days ago", "in 2 weeks", "last month"), never a fixed date, so the demo always looks current. Demo "today" is the real date. `tests/test_demo_data.py` checks this.
- `sts/store.py` `LiveStore.upgrade()`: adds new columns to an older live database on startup and builds journeys for existing tools. Add any new column there too.

## Decision rules (keep tests in tests/test_rules.py in step)

- A decision needs an outcome, a reason and what would change the answer.
- use_existing needs an existing, non-retired tool.
- approve_with_limits needs the limits text.
- approve and approve_with_limits are blocked while the security check is "Needed": "Finish the security check before approving."
- approve and approve_with_limits need the owner agreement checkbox. New tools always start as being_tried.
- "Send without a person checking" = Yes shows a warning, never a block: "Northstar doesn't approve tools that send to customers on their own."
- Ship it: being_tried to approved or approved_with_limits. Retire: any status, replacement optional. Reviewers only.
- "Start a new request from this one" copies task, team, how often, who and information, and sets copied_from.

## Ready to ship rules (keep tests in tests/test_ready_to_ship.py and tests/test_sandbox_web.py in step)

- A being tried tool's page shows reviewers "Ready to ship?" with four items, each done or not done, and a count such as "2 of 4 ready":
  - Owner agreed to own it: from the owner agreement recorded at approval.
  - Security check done or not needed: from the decision that created the tool. If needed and not done, the reviewer records it on the tool (checkbox, date, one-line note).
  - The team kept using it: "Did the team keep using it?" (Yes, regularly / Some of the time / No) plus "Anything go wrong?" (required; "Nothing" is fine). Done only for Yes, regularly or Some of the time.
  - How it was tested: required short answer, optional test results link (http or https only).
- Ship it stays disabled until all four are done, enforced on the server in `ship_tool()`.
- Team stopped using it: no approval options. "A tool the team stopped using isn't ready to ship. Extend the trial or retire it."
- Ship it offers Approved or Approved with limits (limits required).
- Extend and Retire are always available. Extend once only, to no more than 60 days after the current end date. Retire needs a one-line reason; replacement optional.
- Trial ended: being tried and trial end date before today (shown to everyone). Review due: approved and next review month before this month (reviewers only). Both appear under "Needs a decision" on the Review queue and count in the sidebar badge with waiting requests.
- Mark reviewed asks "Still in use?" and "Anything to change?" and sets the next review six months later by default.
- Every change adds a journey event: requested, being_tried, security_done, extended, shipped, reviewed, retired.
- Asked before: the match call may return one past decision id. Send past decisions without requester names; drop any id not in the list sent.
- Demo mode disables Ship it, Extend, Retire, Mark reviewed, recording a security check and saving answers, with a one-line reason.

## Plain language

Use: request, tool, reviewer, decision, being tried, not approved as requested, what would change the answer.

Never show in the interface: intake, triage, ticket, workflow, governance, PII, LLM, model, prompt, deny, denied. They're fine in code, file formats and the README's "Under the hood" section. A test renders every page and checks this.

## Project rules

- A person always decides. Claude never sets an outcome; Claude's response shapes have no outcome field.
- Requester names never appear on Decided before.
- Browser first: never require files, Git or a terminal for the main flow.
- Fictional data only (Northstar Systems, FlowOS, Connect, Insight).
- Demo mode must always work with no key.
- Keys stay server-side: never send them to the browser, log them or commit them.
- No em dashes anywhere: copy, docs, code, Claude instructions, sample data, commit messages. `tests/test_em_dash.py` enforces it.
- Accessible on any screen size (320px with no sideways scroll, 44px targets, labels on every input). No gradients, no emoji. Every color is a CSS custom property in `static/style.css`; status labels always have an icon and words.
- Don't add features beyond the spec without asking.

## Git

Before committing in a fresh clone:

```bash
git config user.name "Juliana Mims"
```

```bash
git config user.email "313165559+jmims-workflow@users.noreply.github.com"
```

End every commit message with a blank line and then:

```
Co-Authored-By: Claude <noreply@anthropic.com>
```

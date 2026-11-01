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
- `demo/`: `tools.yaml`, `requests.yaml`, `recorded/<request-id>.json`. Demo "today" is `as_of` in `requests.yaml`.

## Decision rules (keep tests in tests/test_rules.py in step)

- A decision needs an outcome, a reason and what would change the answer.
- use_existing needs an existing, non-retired tool.
- approve_with_limits needs the limits text.
- approve and approve_with_limits are blocked while the security check is "Needed": "Finish the security check before approving."
- approve and approve_with_limits need the owner agreement checkbox. New tools always start as being_tried.
- "Send without a person checking" = Yes shows a warning, never a block: "Northstar doesn't approve tools that send to customers on their own."
- Ship it: being_tried to approved or approved_with_limits. Retire: any status, replacement optional. Reviewers only.
- "Start a new request from this one" copies task, team, how often, who and information, and sets copied_from.

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

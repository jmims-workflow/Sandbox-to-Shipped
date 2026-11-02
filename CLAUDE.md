# CLAUDE.md

Notes for future sessions working on Sandbox to Shipped.

## What this is

Sandbox to Shipped ("One front door for AI tool requests.") is a FastAPI web app where anyone at a company asks for an AI tool, sees whether an approved tool already does the job, and later sees the decision with a plain reason. Reviewers work one queue with a short checklist and a reason Claude drafts for them to edit. Everyday security checks run automatically against rules the security team writes. Approved tools start as a pilot and get shipped to approved.

Users: requesters (marketers, sellers, support staff; non-engineers), reviewers (the AI tools lead, plus security when the rules send a request to a person), the security team (owns `security_rules.yaml`), and tool owners.

Live site: https://sandbox-to-shipped-103749504031.us-east1.run.app (Cloud Run, preview mode).

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
- Live preview (`STS_MODE=preview` plus `ANTHROPIC_API_KEY`) is for the public site: the demo store (nothing saved, saving buttons off with a one-line reason) with real Claude for exactly three features: the match check (including Asked before and the in-review match), Claude's read on the reviewer view of a just-sent request ("See this request the way a reviewer would", `POST /review/sample`) and "Draft the reason for me". Opening a page never calls Claude, and sending a request in demo or preview doesn't ask for Claude's read. Limits: `STS_DAILY_CLAUDE_CALLS` (default 100, resets at midnight UTC) and `STS_VISITOR_CLAUDE_CALLS_PER_HOUR` (default 10, keyed by a salted hash of the visitor address). Over a limit, or if Claude can't answer, it uses the demo results and shows "Today's live checks are used up, so you're seeing the sample version." Never an error page. Counts are in memory per server, so Cloud Run uses `--max-instances 1`. Preview or live without a key falls back to demo with a notice.
- Live mode needs `STS_MODE=live` and `ANTHROPIC_API_KEY`. Data goes to `DATA_DIR/sts.db`. `sts seed --reset` loads the demo data.
- `STS_REVIEW_DAYS` (default 5) sets "Reviewers usually answer within 5 working days." `STS_PILOT_SLOTS` (default 3) sets how many tools can be in pilot at once. Every setting is in `.env.example`.
- Deploys go to Google Cloud Run (see the README). The container doesn't keep files, so the public site never runs live mode.
- Screenshots: start the app in demo mode, then `node scripts/screenshots.js`.

## Layout

- `sts/provider.py`: every Claude call. Keep all Claude calls here.
- `sts/rules.py`: checklist and decision rules, ready to ship, I need this too. `sts/matching.py`: match validation and the demo word match.
- `sts/security.py` and `security_rules.yaml`: the automatic security check. See "Security rules" below.
- `sts/store.py`: DemoStore (read only) and LiveStore (SQLite). `sts/web.py`: routes. `templates/`, `static/`.
- `demo/`: `tools.yaml`, `requests.yaml`, `examples.yaml` (the three "Try an example" buttons, with recorded results for tasks that aren't demo requests), `recorded/<request-id>.json`. Every demo date is stored as an offset from today ("today", "3 days ago", "in 2 weeks", "last month"), never a fixed date, so the demo always looks current. Demo "today" is the real date. `tests/test_demo_data.py` checks this.
- `sts/store.py` `LiveStore.upgrade()`: adds new columns (tool, request and decision tables) to an older live database on startup and builds journeys for existing tools. Add any new column there too.

## Decision rules (keep tests in tests/test_rules.py in step)

- A decision needs an outcome, a reason and what would change the answer.
- use_existing needs an existing, non-retired tool.
- approve_with_limits needs the limits text.
- The checklist's security item is Not needed, Passed automatically, Needed or Done, prefilled from the request's automatic security check. "Passed automatically" is only accepted for requests that passed; a reviewer can always change it to Needed.
- approve and approve_with_limits are blocked while the security check is "Needed": "Finish the security check before approving."
- approve and approve_with_limits need the owner agreement checkbox. New tools always start as a pilot (being_tried).
- "Send without a person checking" = Yes shows a warning, never a block: "Northstar doesn't approve tools that send to customers on their own."
- Ship it: pilot (being_tried) to approved or approved_with_limits. Retire: any status, replacement optional. Reviewers only.
- "Start a new request from this one" copies task, team, how often, who and information, and sets copied_from.

## Request a tool and what happens next (keep tests in tests/test_examples.py and tests/test_what_next.py in step)

- The form starts empty in every mode. "Not sure what to write? Try an example:" has three links (`/?example=<key>`) that fill the whole form: Follow-up emails, Auto-reply to demo requests, Social posts from case studies. They work without JavaScript.
- The panel is "You may already have what you need". Each match card leads with the outcome: "Claude thinks <tool> is a close match for what you described." (or "...a possible match... Claude is less sure."). The tool link is "Try it before you submit".
- "Here's what happens next": live heading "Request sent"; demo and preview "Here's what would happen next" plus "This is the demo, so nothing was saved." Three steps with status words and icons (Done, Next, Later): Security check (this request's result, from `requester_line()` in `sts/security.py`, code only), A reviewer decides (STS_REVIEW_DAYS, current step), You get a decision. Then "Your request". Demo and preview only: "See this request the way a reviewer would".
- Requesters never see Claude's read. It shows only in the review queue.

## Pilot slots and Not now (keep tests in tests/test_pilot_slots.py and tests/test_not_now.py in step)

- Every tool with status being_tried uses a pilot slot, including pilots past their end date, until shipped or retired.
- The review queue shows "Pilot slots: 2 of 3 used" with links to each pilot; full: "Pilot slots: 3 of 3 used. Ship or retire a pilot to make room."
- When full, approve and approve_with_limits are disabled with "All 3 pilot slots are in use. Ship or retire a pilot first, or choose Not now." and refused on the server in `validate_decision()`. Extending a pilot never needs a free slot.
- not_now ("Not now", pause icon, `--notnow-text` on `--notnow-fill`) needs a reason, what would change the answer and `revisit_on` after today and no more than 6 months away (default 3 months).
- The requester sees "Not now. We'll look at this again in <Month Year>." I need this too works on Not now requests.
- On the revisit date (the date itself counts), the request shows under "Needs a decision": "Revisit: Not now since <date>. Needed by N people." and counts in the badge. The reviewer can reopen it (back to waiting, history and the old decision kept) or decide again. The newest decision counts.
- Decided before shows Not now with its revisit month.

## Ready to ship rules (keep tests in tests/test_ready_to_ship.py and tests/test_sandbox_web.py in step)

- A pilot's page shows reviewers "Ready to ship?" with four items, each done or not done, and a count such as "2 of 4 ready":
  - Owner agreed to own it: from the owner agreement recorded at approval.
  - Security check done or not needed: from the decision that created the tool. Passed automatically counts as done. If needed and not done, the reviewer records it on the tool (checkbox, date, one-line note).
  - The team kept using it: "Did the team keep using it?" (Yes, regularly / Some of the time / No) plus "Anything go wrong?" (required; "Nothing" is fine). Done only for Yes, regularly or Some of the time.
  - How it was tested: required short answer, optional test results link (http or https only).
- Ship it stays disabled until all four are done, enforced on the server in `ship_tool()`.
- Team stopped using it: no approval options. "A tool the team stopped using isn't ready to ship. Extend the pilot or retire it."
- Ship it offers Approved or Approved with limits (limits required).
- Extend and Retire are always available. Extend once only, to no more than 60 days after the current end date. Retire needs a one-line reason; replacement optional.
- Pilot ended: in pilot and end date before today (shown to everyone). Review due: approved and next review month before this month (reviewers only). Both appear (with Not now revisits) under "Needs a decision" on the Review queue and count in the sidebar badge with waiting requests.
- Mark reviewed asks "Still in use?" and "Anything to change?" and sets the next review six months later by default.
- Every change adds a journey event: requested, being_tried, security_done, extended, shipped, reviewed, retired.
- Asked before: the match call may return one past decision id. Send past decisions without requester names; drop any id not in the list sent.
- Demo and preview modes disable Ship it, Extend, Retire, Mark reviewed, recording a security check, saving answers, Send decision, Save for later, Reopen it, questions and I need this too, with a one-line reason.

## Pilot wording

- Users see "pilot", never "being tried": the label "In pilot", "Pilot ends <date>", "Pilot ended", "Pilot started", "Pilot extended", "Extend the pilot", the inventory filter "In pilot".
- Internal names stay: `being_tried`, `trial_ends`, `trial_extended`, `trial_ended`, the journey kind `being_tried`. Don't rename them in code or data files.
- There is no "sandbox" line anywhere in the interface. The How it works path is: Request, Check what exists, Reviewer decides, Pilot, Ready to ship check, Approved, with a side path: Reviewer decides, Not now, Revisit date, back to Reviewer decides.

## Security rules (keep tests in tests/test_security.py in step)

- `security_rules.yaml` is owned by the security team. Change it only with their OK. It lists approved AI services (Northstar: Claude and Meridian Assist) and, for each information kind, none, automatic or person. Northstar: public_only none; internal_notes, customer_contact, deal_pricing automatic; sensitive_personal person.
- It is validated with Pydantic at startup; a problem stops the app with a message naming the field. `sts check-data` checks it too.
- Any information kind other than public_only shows "A few questions for security": sends without a person checking (Yes/No/Not sure), keeps information outside approved tools (Yes/No/Not sure), which AI service (approved services, Something else, Not sure). Answers are required then.
- `check_security()` in `sts/security.py`, plain code, Claude never involved: only public information is "not needed"; any sensitive_personal goes to a person whatever the answers; otherwise it passes only when both answers are No and the service is approved; any Yes, Not sure or unapproved service goes to a person, and the reasons name each answer that did.
- The result is saved on the request (`security_answers`, `security_result`), shown in the review queue and fills the checklist.
- Early warnings on Request a tool come from rules in code (`early_warnings()`), never from Claude, never a score or prediction, and never block submitting.

## I need this too (keep tests in tests/test_need_too.py in step)

- The match call may also return one request still waiting or in review. Send open requests as id, title and task only, never names, and leave out the person's own requests and ones they're already on. Drop any id not in the list sent.
- Live: adds the person to `needed_by` (once, never their own request, only while open). They see it under "Requests I need too" on My requests. Reviewers see "Needed by N people" (requester plus everyone added) and each added person's note. Requesters never see who else is attached.
- The button is "I need this too". Never "Me too", "upvote" or "like", and no thumbs icon.

## Plain language

Use: request, tool, reviewer, decision, pilot, not approved as requested, what would change the answer.

Never show in the interface: intake, triage, ticket, workflow, governance, PII, LLM, model, prompt, deny, denied, being tried. They're fine in code, file formats and the README's "Under the hood" section. A test renders every page and checks this.

## Project rules

- A person always decides. Claude never sets an outcome; Claude's response shapes have no outcome field.
- Warnings and the security check come from code, never from Claude.
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

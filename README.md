# Sandbox to Shipped

**One front door for AI tool requests.**

Try it live: https://sandbox-to-shipped-103749504031.us-east1.run.app

Sandbox to Shipped is a small web app that gives a company one place to ask for AI tools. Anyone can ask for a tool, see right away whether an approved tool already does the job, and later see the decision with a plain reason. Reviewers get one queue, a short checklist and a reason Claude drafts for them to edit. Everyday security checks run automatically against rules the security team writes. Approved tools land in a shared inventory and start as a pilot. They are approved for everyone only after a short ready to ship check.

The demo uses a fictional company, Northstar Systems, and its products FlowOS, Connect and Insight. Every person and tool in it is made up.

![Request a tool, with Call Recap Writer shown as a close match](docs/screenshots/request-a-tool.png)

## The problem

When people want an AI tool, they ask in chat, in email, in a hallway. The same idea gets asked for three times. Answers take weeks, and when the answer is no, nobody says why or what would make it a yes. Meanwhile the company may already have a tool that does the job, and nobody knows who owns it.

## Who it is for

- **Requesters:** marketers, sellers, support staff, anyone with an idea for an AI tool. They want a fast answer, and if the answer is no, a reason and a way forward. They never need GitHub, files or a terminal.
- **Reviewers:** the person who leads AI tools for the company, plus someone from security when a request needs a person to look. They want fewer duplicate requests, a consistent way to decide, and less time writing explanations.
- **The security team:** they write the security rules the app applies to every request, and review the requests the rules send to a person.
- **Tool owners:** the person responsible for a tool after it is approved, listed in the inventory so people know who to ask.

## How it works

1. **Request a tool.** Someone describes the task (not the tool), their team, how often they'd do it, who would use it and what information it would touch. If it uses anything other than public information, three short questions for security appear.
2. **Check what exists.** As they type, the app shows up to two approved tools that may already do the job, and how sure Claude is. If a match is close but not quite right, they say what's missing in the same form. If someone already asked for the same thing and it's still in review, they can say **I need this too** instead of starting a new request.
3. **The security check runs.** Plain code applies security's rules to the answers. See "The automatic security check" below.
4. **A reviewer decides.** The request lands in the review queue with Claude's quick read and the security check result. The reviewer answers a four-question checklist, picks an outcome and edits a reason Claude drafted. The requester sees the decision, the reason and what would change the answer.
5. **Pilot.** An approved tool starts as a pilot with one team, an owner who agreed to own it and an end date.
6. **Ready to ship check.** On the tool's page, a reviewer works through four items: the owner agreed, security is covered, the team kept using it, and how it was tested. "Ship it" stays off until all four are done.
7. **Approved.** The reviewer ships it to approved (or approved with limits). The tool page keeps the answers under "How it earned approval", and every tool shows its journey from request to today.

Pilots that run past their end date and reviews that come due show up under **Needs a decision** at the top of the review queue, so nothing sits in a pilot or the inventory forever. When someone types a request, the app also shows a related past decision, if there is one, as **Asked before**.

Every past decision is listed on **Decided before**, without the requester's name, so nobody has to ask twice.

### The automatic security check

The security team owns one file, `security_rules.yaml`. It lists the AI services security has approved (for Northstar: Claude, and Meridian Assist, Northstar's private instance) and, for each kind of information, one of three rules: no check, an automatic check, or always a person.

When a request uses anything other than public information, the form asks three questions:

- Would it send anything to customers or the public without a person checking first? (Yes, No, Not sure)
- Would it keep information anywhere other than tools Northstar already approved? (Yes, No, Not sure)
- Which AI service would it use? (the approved services, Something else, or Not sure)

Then the app works out the result, in code:

- **Only public information:** "Security check: not needed".
- **Any sensitive personal information** (student records, health details, government IDs): "Security check: a person from security will review this", whatever the answers.
- **Otherwise** it passes automatically only when the first two answers are No and the service is an approved one: "Security check: passed automatically against security's rules".
- **Any Yes, Not sure or unapproved service** sends it to a person, and the result names which answer did.

The result is saved with the request, shown in the review queue and fills the security item in the reviewer's checklist. A reviewer can still change "Passed automatically" to "Needed". No tool is approved while the security check is Needed. Claude is not involved in this check.

### What reviewers look for, and early warnings

Under the form, a collapsible **What reviewers look for** section lists the short version: whether a tool we have already does it, whether it would send anything to customers on its own (Northstar doesn't approve that), what information it uses under security's rules, and that approved tools start as a pilot.

Two plain warnings appear next to the answers that trigger them, before anyone submits. They come from rules in code, never from Claude, and they are never a score or a prediction. The requester can always submit anyway.

- Sends to customers without a person checking: "Heads up: Northstar doesn't approve tools that send to customers on their own. A version that drafts for a person to check and send is much more likely to be approved."
- Sensitive personal information: "Requests with sensitive personal information always get a review from security, so expect this one to take longer."

## Design choices and why

1. **One front door.** Requests, decisions and approved tools live in one place, so nobody has to chase an answer in chat.
2. **Check what exists first.** Before anyone submits, the app shows approved tools that may already do the job. Often the best answer is a tool the company already has.
3. **A person decides every request.** Claude sizes up requests, suggests matches and drafts reasons. It never approves or turns down anything on its own.
4. **Security writes the security rules.** Everyday requests don't wait on a person: code applies security's rules to the answers. Sensitive information always goes to a person.
5. **Every "no" comes with a reason and a path.** Each decision says why, and what would change the answer.
6. **Ask what people actually know.** The form asks how often and who would use it, not how many hours it would save, because people guess hours badly.
7. **One request per idea.** "I need this too" adds people to a request already in review, so reviewers see how many people need it instead of three copies.
8. **Past decisions are open, requesters stay private.** "Decided before" shows every past decision and its reason so people do not ask twice, but never shows who asked. Requesters never see who else needs a request.
9. **Owners agree to be owners.** Nobody is listed as a tool owner unless they agreed to it.
10. **Shipped means it earned it.** Every new tool starts as a pilot: one team, a named owner and an end date. It moves to approved only after a reviewer confirms the owner agreed, security is covered, the team kept using it, and how it was tested. Pilots that run out and reviews that come due are flagged.
11. **Demo mode uses the real logic.** It runs recorded Claude results through the same matching, security, checklist and decision code as live mode.
12. **Honest about the alternative.** The cheapest version of this is a shared form and a spreadsheet. This app earns its place with the check for existing tools, the automatic security check, drafted reasons, and a decision history people can search.

## What you can try in the demo

The public site at https://sandbox-to-shipped-103749504031.us-east1.run.app is open to anyone and runs in live preview mode. The existing-tool check (with Asked before and I need this too), Claude's read on "Here's what happens next" and "Draft the reason for me" use real Claude, within daily limits. Nothing is saved: the buttons that would save something are turned off, with a line saying why. When the day's live checks are used up, the site quietly shows the recorded sample results instead.

A visitor can use every page and switch between Requester and Reviewer. Some things to try:

- On **Request a tool**, the prefilled example finds Call Recap Writer. Replace the text with "auto-reply to demo requests" to see an **Asked before** card.
- Type "posts for social media from our case studies" to see **I need this too** for a request already in review.
- Check **Sensitive personal information**, or answer Yes to "Would it send anything to customers...", to see the early warnings. Open **What reviewers look for** under the form.
- As a reviewer, the **Review queue** shows each security result: Social posts from case studies passed automatically and is needed by 3 people; Renewal risk notes for CSMs goes to a person because the AI service answer was "Not sure"; Answer employee benefits questions goes to a person because it uses health details.
- Open **Translation Helper** to see the Ready to ship card at 2 of 4, with Ship it turned off.
- The **Review queue** starts with Needs a decision: Partner Outreach Drafts (pilot ended) and Proposal Drafter (review due).
- **Webinar Invite Writer** shows a full journey and how it earned approval.

Demo dates are stored as offsets from today, so the examples always look current.

## What was tested with saving turned on

Live mode was tested with a stand-in for Claude: the tests swap in a fake client that returns fixed answers, then save requests (with their security answers and results), decisions, "I need this too", ready to ship answers, pilot extensions, reviews and retirements to a real SQLite file and read them back. Live preview was tested the same way, including both limits. The shape of each Claude request was checked in those tests too.

## Run it

You need Python 3.12 or newer.

```bash
pip install -e ".[dev]"
```

### Demo mode (no key needed)

Demo mode is the default. It needs no API key, makes no calls to Claude and saves nothing. It loads the sample data in `demo/` fresh on every start, so anyone can click around without breaking anything.

```bash
sts serve
```

Open http://localhost:8080. Use **Viewing as** at the bottom of the sidebar to switch between Requester and Reviewer.

### Live preview mode (real Claude, nothing saved)

Live preview is for a public site. It behaves exactly like demo mode (sample data, nothing saved, saving buttons off), except that three features use real Claude: the existing-tool check (including Asked before and I need this too), Claude's read on "Here's what happens next", and "Draft the reason for me".

```bash
export STS_MODE=preview
export ANTHROPIC_API_KEY=your-key-here
sts serve
```

Two limits keep the cost down. Both are counted in the app:

- `STS_DAILY_CLAUDE_CALLS` (default 100): Claude calls per day for the whole site, reset at midnight UTC.
- `STS_VISITOR_CLAUDE_CALLS_PER_HOUR` (default 10): Claude calls per visitor per hour. Visitors are told apart by a one-way hash of their address; the address itself is never kept.

When either limit is reached, the app quietly uses the recorded demo results or the demo word match and shows "Today's live checks are used up, so you're seeing the sample version." It never shows an error page for this. If `STS_MODE=preview` is set but `ANTHROPIC_API_KEY` is missing, the app runs the demo and shows a notice saying so.

### Live mode

Live mode calls Claude and saves requests, decisions and tool changes to a SQLite file in `DATA_DIR`. Copy `.env.example` to `.env` (it is ignored by git) or set the variables in your shell:

```bash
export STS_MODE=live
export ANTHROPIC_API_KEY=your-key-here
export DATA_DIR=./data
```

Optionally load the sample data into the database first. It asks before replacing anything:

```bash
sts seed --reset
```

Then start the app:

```bash
sts serve
```

On the first visit the app asks for a display name. It is stored in a browser cookie and used as the requester or reviewer name.

If `STS_MODE=live` is set but `ANTHROPIC_API_KEY` is missing, the app falls back to demo mode and shows a notice. The key is only read on the server; it is never sent to the browser, logged or committed. Visitor text is never logged either.

| Variable | Default | What it does |
| --- | --- | --- |
| `STS_MODE` | `demo` | `demo`, `preview` or `live`. Demo stays demo even when a key is present. |
| `ANTHROPIC_API_KEY` | (empty) | Needed for preview and live. |
| `STS_MODEL` | `claude-sonnet-5-5` | The Claude model used in preview and live. |
| `DATA_DIR` | `./data` | Folder for the SQLite file in live mode. |
| `STS_REVIEW_DAYS` | `5` | Shown on "Here's what happens next": "Reviewers usually answer within 5 working days." |
| `STS_DAILY_CLAUDE_CALLS` | `100` | Live preview: Claude calls per day for the whole site. |
| `STS_VISITOR_CLAUDE_CALLS_PER_HOUR` | `10` | Live preview: Claude calls per visitor per hour. |
| `PORT` | `8080` | Port the server listens on. |

### Change the security rules

Security edits `security_rules.yaml` at the root of the repository. The app checks the file when it starts and will not start if something is wrong, with a message that names the line to fix, for example `security_rules.yaml, information.deal_pricing: use none, automatic or person`.

### Check the demo data and security rules

```bash
sts check-data
```

Problems are reported with the file and field, for example `demo/tools.yaml, tools[8].status: Input should be 'being_tried', 'approved', 'approved_with_limits' or 'retired'`. (`being_tried` is the internal name for a pilot.)

### Run the tests

```bash
pytest
```

The tests cover the matching rules, every decision rule, every path through the security check and the rules file checks, the early warnings, I need this too, live preview (nothing saved, Claude only for three features, both limits, falling back without a key), the ready to ship check (Ship it refused on the server until all four items are done), extending a pilot, Retire, Mark reviewed, Pilot ended and Review due at the date edges, the badge count, Asked before, each tool's journey, demo dates relative to today, upgrading a database from earlier versions, copying a request, privacy on Decided before and for Claude's read, demo mode making no network calls and saving nothing, demo data checks, the 5,000 character limit, the plain-language word list (including "being tried") and a scan for em dashes. Live and preview modes are tested with a fake Claude client, so the tests never call the real API. A GitHub Actions workflow runs them on every pull request.

### Run with Docker

```bash
docker build -t sandbox-to-shipped .
```

```bash
docker run -p 8080:8080 -e STS_MODE=demo sandbox-to-shipped
```

The container serves on `PORT` (default 8080). `/health` returns `ok`.

## Deploying to Google Cloud Run

These steps are for someone new to Google Cloud. They use Cloud Shell, a terminal in your browser that already has the `gcloud` command and is signed in to your account, so you don't need to install anything.

### Deploy the demo

1. Go to https://console.cloud.google.com and sign in. If you don't have a project yet, create one from the project picker at the top of the page. Cloud Run needs billing turned on for the project.
2. Click the **Activate Cloud Shell** button (a terminal icon) at the top right. A terminal opens at the bottom of the page.
3. Get the code and deploy it. Paste these into Cloud Shell:

```bash
git clone https://github.com/jmims-workflow/Sandbox-to-Shipped.git && cd Sandbox-to-Shipped
```

```bash
gcloud run deploy sandbox-to-shipped --source . --region us-east1 --allow-unauthenticated --set-env-vars STS_MODE=demo
```

4. If `gcloud` asks to turn on APIs (such as Cloud Run, Cloud Build or Artifact Registry) or to create a repository for the built image, answer `y`. Building from source uses the `Dockerfile` in the repository.
5. When it finishes, it prints a **Service URL**. Open it. You should see Request a tool with "Demo: sample data" in the sidebar.

Cloud Run sets the `PORT` variable for you, and the app listens on it.

### Run the public site in live preview mode

Live preview shows real Claude results without saving anything. The API key is stored in Secret Manager, so it never appears in your command history, the service settings or the browser.

1. In Cloud Shell, turn on Secret Manager:

```bash
gcloud services enable secretmanager.googleapis.com
```

2. Store your Claude API key as a secret named `anthropic-api-key`. Replace `your-key-here` with your key. `printf` avoids adding a line break to the key:

```bash
printf "your-key-here" | gcloud secrets create anthropic-api-key --data-file=-
```

3. Give the Cloud Run service permission to read that secret. By default a Cloud Run service runs as the project's default compute service account, `PROJECT_NUMBER-compute@developer.gserviceaccount.com`. This finds your project number and grants the Secret Manager Secret Accessor role on this one secret:

```bash
PROJECT_NUMBER=$(gcloud projects describe $(gcloud config get-value project) --format='value(projectNumber)')
```

```bash
gcloud secrets add-iam-policy-binding anthropic-api-key --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"
```

4. Deploy in preview mode, with the key passed as a secret and at most one running copy of the app. One copy keeps the daily count accurate, because each copy counts on its own:

```bash
gcloud run deploy sandbox-to-shipped --source . --region us-east1 --allow-unauthenticated --set-env-vars STS_MODE=preview --update-secrets=ANTHROPIC_API_KEY=anthropic-api-key:latest --max-instances 1
```

5. Open the Service URL. The sidebar now says "Live preview: real Claude, nothing saved". To change the limits, add them to `--set-env-vars`, for example `--set-env-vars STS_MODE=preview,STS_DAILY_CLAUDE_CALLS=50`.

6. **Set a monthly spend limit as a backstop.** The app's limits reset when the server restarts, so also cap spending on the Claude side. In the Claude Console, open the **Billing** page (https://platform.claude.com/settings/billing), find **Spend limits** and click **Set limit** (or **Adjust limit**). Pick a monthly amount you're comfortable with. Requests stop for the rest of the month once it's reached, and the site falls back to the sample results.

To replace the key later, add a new version of the secret and deploy again:

```bash
printf "your-new-key" | gcloud secrets versions add anthropic-api-key --data-file=-
```

**Keep the public site in demo or preview mode.** A container on Cloud Run doesn't keep files between restarts, so live mode would lose its SQLite data. Live mode on Cloud Run would need a database outside the container (see Known limitations).

## Under the hood

For technical readers, here is how the plain words in the app map to familiar ideas.

- **Requests** are an intake queue. Each request records what the requester saw before submitting (the matches and their "what's missing" note), the answers to the security questions and the security check result, Claude's read, a timeline, any questions and anyone added with "I need this too".
- **The existing-tool check** is retrieval plus an LLM match with id validation. Claude gets the inventory of tools that are approved, approved with limits or in pilot, and returns up to two tool ids with a confidence of "close" or "possible". Code then drops any id that is not in that inventory, so a made-up or retired tool can never appear. In demo mode, recorded results or a simple word-overlap match go through the same validation.
- **The automatic security check** is a policy-as-code rule set. `security_rules.yaml` is validated with Pydantic at startup (unknown keys, missing information kinds, bad values and duplicate service ids are all reported with the field), and `check_security()` in `sts/security.py` applies it. No model is called. The early warnings on Request a tool come from the same module.
- **The reviewer** is a human-in-the-loop approval step. Claude's structured outputs have no outcome field, the outcome only ever comes from the reviewer's form, and a test scans the code for any assignment of an outcome. `validate_decision()` blocks approvals while the security check is Needed, and only accepts "Passed automatically" for requests that passed.
- **I need this too** is deduplication. The same match call also gets the requests still waiting or in review (id, title and task; never names) and may return one id with a reason. Code drops any id not in the list sent, and leaves out the person's own requests. Adding a person is a server-side rule (`add_needed_by()`): once per person, never to their own request, only while it's open.
- **Pilot** is a sandbox stage (internally `being_tried`). Every approval creates a tool in that state, with an owner who agreed and an end date (`trial_ends`). "Ship it" promotes it.
- **The ready to ship check** is a promotion gate enforced on the server. `ship_tool()` in `sts/rules.py` refuses until all four items are done, and refuses outright when the team stopped using the tool, whatever the page shows. Extending (once, up to 60 days) and retiring (with a reason) are always open.
- **Needs a decision** is stale-item monitoring: pilots past their end date and approved tools past their review month are flagged on the tool page, in the inventory and at the top of the review queue, and counted in the sidebar badge.
- **Asked before** is retrieval over past decisions with id validation. The same match call gets the past decisions (title, task, outcome, reason, what would change; never the requester's name) and may return one decision id with a reason. Code drops any id that was not in the list sent.
- **Live preview** wraps the Claude provider with an in-memory rate limiter: a daily counter that rolls over at midnight UTC and a sliding one-hour window per visitor, keyed by a salted SHA-256 hash of the visitor's address (the first `X-Forwarded-For` entry on Cloud Run). Over the limit, or if Claude can't answer, it uses the demo provider. The store is the read-only demo store, so nothing can be saved.
- **Each tool's journey** is an event log kept on the tool (requested, pilot started, security check done, pilot extended, shipped, reviewed, retired), shown as an ordered list.
- **Database upgrades** run on startup in live mode: new columns are added to a database from an earlier version without touching existing rows, and existing tools get a journey built from their request, decision and status.
- **Decided before** is a public decision log with requester privacy. The page is built only from the title, outcome, reason, what would change and date; a test checks that no requester name is rendered.

Code layout:

| Path | What it holds |
| --- | --- |
| `sts/provider.py` | Every Claude call (find_matches, size_up, draft_reason), the demo player and the live preview limiter. The only file that talks to Claude. |
| `sts/security.py` | Loading and checking `security_rules.yaml`, the automatic security check and the early warnings. |
| `sts/matching.py` | Match validation and the demo word match. |
| `sts/rules.py` | The checklist and decision rules, the ready to ship check, Ship it, Extend, Retire, Mark reviewed, Pilot ended and Review due, I need this too, copying a request. |
| `sts/store.py` | Demo store (in memory, read only) and live store (SQLite via SQLModel). |
| `sts/web.py` | FastAPI routes. Pages are server-rendered Jinja2 templates in `templates/`. |
| `sts/cli.py` | The `sts` command. |
| `security_rules.yaml` | Security's rules, owned by the security team. |
| `demo/` | `tools.yaml`, `requests.yaml` and `recorded/<request-id>.json` (recorded Claude output). Dates are offsets from today, such as "3 days ago" or "in 2 weeks". |

Claude calls use the official `anthropic` Python SDK with structured outputs (`messages.parse` with a Pydantic model), so every response parses. Request text is wrapped in `<request_data>` delimiters and Claude is told to treat it as data and ignore any instructions inside it. Matching and size-ups use low effort for quick, steady answers; current Claude models no longer accept a temperature setting, so effort is the lever instead. Calls opt in to the API's default refusal fallback.

The interface is plain HTML and CSS with a little vanilla JavaScript (the live match check, showing the security questions and early warnings as you answer, and the "Draft the reason for me" button). Every form also works without JavaScript, and the phone menu is a `details` element.

## Screenshots

Request a tool, with the match panel:

![Request a tool](docs/screenshots/request-a-tool.png)

Request a tool with the security questions, both early warnings and the "I need this too" card:

![Request a tool with the security questions and I need this too](docs/screenshots/request-security-need-too.png)

A request that was not approved as requested, with the reason and what would change the answer:

![Not approved request](docs/screenshots/not-approved-request.png)

Tool inventory:

![Tool inventory](docs/screenshots/tool-inventory.png)

Review queue, with Needs a decision at the top, then the request's details, the security check result, who else needs it, Claude's read and the checklist:

![Review queue with Needs a decision](docs/screenshots/review-queue.png)

A tool in pilot, Translation Helper, with the Ready to ship card at 2 of 4:

![Ready to ship card](docs/screenshots/tool-ready-to-ship.png)

Webinar Invite Writer, with how it earned approval and its journey:

![Webinar Invite Writer's journey](docs/screenshots/tool-journey.png)

A request page at phone width:

<img src="docs/screenshots/request-page-phone.png" alt="A request page at phone width" width="390">

To refresh them, start the app in demo mode and run `node scripts/screenshots.js` (needs Playwright).

## Known limitations

- **No real sign-in.** "Viewing as" and the display name are cookies anyone can change, so a live instance is for one person or a trusted team. Real sign-in would be the first thing to add. It also means "I need this too" goes by display name.
- **The automatic security check is only as good as the answers on the request.** If someone answers No when the honest answer is Yes, the request can pass automatically. Reviewers can still change "Passed automatically" to "Needed", and security can tighten the rules file.
- **Claude's matches can be wrong or miss a tool.** That's why a reviewer sees what the requester was shown and makes the call.
- **The demo's word match is much simpler than live mode.** Only the prefilled example uses recorded Claude results.
- **A single SQLite file suits a small team, not a large company.**
- **The site on Cloud Run never saves.** A Cloud Run container doesn't keep files, so saved data would need a database outside the container. The public site runs in preview mode, which saves nothing.
- **Live preview limits are counted per server and reset when it restarts.** That's why the deploy uses `--max-instances 1`, and why a spend limit in the Claude Console is the real backstop. The per-visitor limit trusts the first `X-Forwarded-For` address, which a determined visitor can change; the daily limit still holds.
- **Decided before is visible to everyone,** so reasons should be written for a wide audience.
- **Demo data is fictional and hand-written,** including the recorded Claude output.
- **The ready to ship answers are recorded by the reviewer, not measured by the app.** "The team kept using it" is the reviewer's answer, not usage data.
- **Test results are a link, not checked by the app.** The app only checks that it is an http or https address.
- **The tests never call the real Claude API.** Live and preview modes were tested with a fake Claude client. See "What was tested with saving turned on".

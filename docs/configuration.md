# Configuration

[Back to the README](../README.md)

You need Python 3.12 or newer.

```bash
pip install -e ".[dev]"
```

Copy `.env.example` to `.env` (it is ignored by git) or set the variables in your shell. The key is only read on the server; it is never sent to the browser, logged or committed. Visitor text is never logged either.

## Settings

| Variable | Default | What it does |
| --- | --- | --- |
| `STS_MODE` | `demo` | `demo`, `preview` or `live`. Demo stays demo even when a key is present. |
| `ANTHROPIC_API_KEY` | (empty) | Needed for preview and live. |
| `STS_MODEL` | `claude-sonnet-5-5` | The Claude model used in preview and live. |
| `DATA_DIR` | `./data` | Folder for the SQLite file in live mode. |
| `STS_REVIEW_DAYS` | `5` | Shown on "Here's what happens next": "Reviewers usually answer within 5 working days." |
| `STS_PILOT_SLOTS` | `3` | How many tools can be in pilot at once. Approvals are refused while every slot is in use. |
| `STS_DAILY_CLAUDE_CALLS` | `100` | Live preview: Claude calls per day for the whole site. |
| `STS_VISITOR_CLAUDE_CALLS_PER_HOUR` | `10` | Live preview: Claude calls per visitor per hour. |
| `PORT` | `8080` | Port the server listens on. |
| `STS_FAKE_CLAUDE` | (empty) | Development only. `1` makes live mode use the stand-in for Claude, with no key and no network calls. Used by the recorded walkthrough. See below. |

## Demo mode (no key needed)

Demo mode is the default. It needs no API key, makes no calls to Claude and saves nothing. It loads the sample data in `demo/` fresh on every start, so anyone can click around without breaking anything.

```bash
sts serve
```

Open http://localhost:8080. Use **Viewing as** at the bottom of the sidebar to switch between Requester and Reviewer.

## Live preview mode (real Claude, nothing saved)

Live preview is for a public site. It behaves exactly like demo mode (sample data, nothing saved, saving buttons off), except that three features use real Claude: the existing-tool check (including Asked before and I need this too), Claude's read on the reviewer view of a request you just sent, and "Draft the reason for me". Requesters never see Claude's read, so sending a request doesn't ask Claude for one; it is made only when someone presses "See this request the way a reviewer would".

```bash
export STS_MODE=preview
```

```bash
read -s -p "Claude API key: " ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY && echo
```

```bash
sts serve
```

Two limits keep the cost down. Both are counted in the app:

- `STS_DAILY_CLAUDE_CALLS` (default 100): Claude calls per day for the whole site, reset at midnight UTC.
- `STS_VISITOR_CLAUDE_CALLS_PER_HOUR` (default 10): Claude calls per visitor per hour. Visitors are told apart by a one-way hash of their address; the address itself is never kept.

When either limit is reached, the app quietly uses the recorded demo results or the demo word match and shows "Today's live checks are used up, so you're seeing the sample version." It never shows an error page for this. If `STS_MODE=preview` is set but `ANTHROPIC_API_KEY` is missing, the app runs the demo and shows a notice saying so.

## Live mode

Live mode calls Claude and saves requests, decisions and tool changes to a SQLite file in `DATA_DIR`.

```bash
export STS_MODE=live DATA_DIR=./data
```

Set `ANTHROPIC_API_KEY` as above. Optionally load the sample data into the database first. It asks before replacing anything:

```bash
sts seed --reset
```

Then start the app:

```bash
sts serve
```

On the first visit the app asks for a display name. It is stored in a browser cookie and used as the requester or reviewer name.

If `STS_MODE=live` is set but `ANTHROPIC_API_KEY` is missing, the app falls back to demo mode and shows a notice.

## The stand-in for Claude (development only)

`STS_FAKE_CLAUDE=1` makes live mode use the stand-in Claude client in `sts/fake_claude.py`, which returns fixed answers and never opens a network connection. It exists so the recorded walkthrough is repeatable and needs no key. The app refuses to start, and says why, when:

- `STS_FAKE_CLAUDE` is set and `STS_MODE` is `demo` or `preview`, or
- `STS_FAKE_CLAUDE` is set and `ANTHROPIC_API_KEY` is also set.

The app's pages never mention it. Never set it on a deployed site.

## Change the security rules

Security edits `security_rules.yaml` at the root of the repository. The app checks the file when it starts and will not start if something is wrong, with a message that names the line to fix, for example `security_rules.yaml, information.deal_pricing: use none, automatic or person`.

## Check the demo data and security rules

```bash
sts check-data
```

Problems are reported with the file and field, for example `demo/tools.yaml, tools[8].status: Input should be 'being_tried', 'approved', 'approved_with_limits' or 'retired'`. (`being_tried` is the internal name for a pilot.)

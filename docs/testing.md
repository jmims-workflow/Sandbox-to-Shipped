# Testing

[Back to the README](../README.md)

There are 365 automated tests, and they all pass. A GitHub Actions workflow (`.github/workflows/tests.yml`) runs them on every pull request and every push to main.

```bash
pytest
```

## What the tests cover

- **Rules** (`tests/test_rules.py`): every decision rule. A decision needs an outcome, a reason and what would change the answer; use an existing tool needs a tool that isn't retired; approve with limits needs the limits; approvals are refused while security screening is Needed and need the owner agreement; "Passed automatically" only for requests that passed.
- **Security screening** (`tests/test_security.py`): every path through screening (not needed, passed, sent to a person, each answer named in the reasons), the rules file checks with the field named in each problem, and the early warnings.
- **Matching** (`tests/test_matching.py`): match validation drops ids that were not sent, retired tools never appear, and the demo word match.
- **Requests and what happens next** (`tests/test_request_flow.py`, `tests/test_examples.py`, `tests/test_what_next.py`): the form starts empty, each example fills the whole form, each screening result on "Here's what happens next", the 5,000 character limit, and Claude's read never shown to requesters.
- **I need this too** (`tests/test_need_too.py`): adding people once, never to their own request, only while open, the counts reviewers see, notes, and privacy.
- **Pilot slots** (`tests/test_pilot_slots.py`): counting, the 3 of 3 message, approvals refused on the server when full, extending allowed.
- **Not now** (`tests/test_not_now.py`): the revisit date rules, the revisit at the date edges, reopening with history kept, I need this too on a Not now.
- **Ready to ship** (`tests/test_ready_to_ship.py`, `tests/test_sandbox_web.py`): Ship it refused on the server until all four items are done, extending a pilot, Retire, Mark reviewed, Pilot ended and Review due at the date edges, each tool's journey, and the badge count.
- **Live mode** (`tests/test_live.py`, `tests/test_upgrade.py`): saving requests (with their security answers and results), decisions, "I need this too", ready to ship answers, pilot extensions, reviews and retirements to a real SQLite file and reading them back; upgrading a database from earlier versions; copying a request.
- **Live preview** (`tests/test_preview.py`): nothing saved, Claude only for three features, both limits, falling back without a key.
- **The stand-in for Claude** (`tests/test_fake_claude.py`): `STS_FAKE_CLAUDE` works in live mode with no key and no network calls, and the app refuses to start with it in demo or preview mode or next to a real key, saying why.
- **Claude never decides** (`tests/test_no_claude_outcome.py`): a scan of the code for any assignment of an outcome from Claude's answers.
- **Demo mode and wording** (`tests/test_web_demo.py`, `tests/test_demo_data.py`): every page renders; demo mode makes no network calls and saves nothing; demo dates are relative to today; privacy on Decided before (no requester names) and for Claude's read; the plain-language word list, including "being tried" and "security check", on every page.
- **Docs** (`tests/test_readme.py`): the README keeps its opening, My role and Part of a set sections word for word and stays short; every relative link in the README and in `docs/` points to a file that exists; the design principles and Why standards paragraph are kept.
- **No em dashes** (`tests/test_em_dash.py`): a scan of every text file.
- **The matching evaluation's own code** (`tests/test_eval_matching.py`): the case file loads and every tool, decision and request id in it exists; every category has at least 3 cases; each scoring measure on hand-built answers, including cases that expect no tool and injection cases; the command refuses without a key, refuses the stand-in next to a real key, enforces `--max-calls` and never prints the key; the baseline makes no network calls; and a full run against the stand-in writes both report files.

## A stand-in for Claude

The tests never call the real Claude API. Live and preview modes are tested with a stand-in client (`sts/fake_claude.py`) that returns fixed structured answers. The tests also check the shape of each request sent to Claude. That means the tests show the app's rules and storage work; they don't measure how good Claude's matches are. The matching evaluation below does that.

## End to end

- **The recorded walkthrough** ([docs/walkthrough.mp4](walkthrough.mp4)) is the end-to-end demonstration: a request, both server refusals, a pilot and a shipped tool, recorded in a real browser on a local copy in live mode with the stand-in for Claude. Rerun it with `node scripts/walkthrough.js` (needs Node, Playwright and ffmpeg). It is not run in GitHub Actions.
- **The example buttons** are checked in a real browser with JavaScript on by `node scripts/check_examples.js` against a running app. `pytest` runs it too when Node and Playwright are installed, and skips it otherwise.
- **Screenshots** are refreshed with `node scripts/screenshots.js` against the app in demo mode.

## The matching evaluation

The unit tests check that the app handles Claude's answers safely. They can't say whether Claude's suggestions are any good. The matching evaluation does: `sts eval-matching` runs about 30 labeled requests (in `evals/matching_cases.yaml`) through the real match check and scores the tool suggestions, "Asked before" and "I need this too". `sts eval-matching --baseline` runs the same cases through the simple word match, so Claude can be compared with it. Reports are in `evals/results/`.

How it differs from the unit tests:

- **Real Claude, not the stand-in.** It needs `ANTHROPIC_API_KEY`, makes real calls and costs a little money each run. It asks before making any call and stops above `--max-calls`.
- **Scored, not pass or fail.** It reports how often the top suggestion was right, how often an expected tool was missed or a wrong one suggested, and how the related request and decision did, overall and by category.
- **Run by hand, never in GitHub Actions.** It is run on purpose, for example after a change to the model or the matching instructions, and the dated report is saved with the case set's hash so runs can be compared.
- **Measure, don't tune.** The case set measures matching as it is. Changing the instructions to raise the score is a separate change, compared before and after with the same set.

See [evals/README.md](../evals/README.md) for what each category tests, how to read a report and how to run it in Google Cloud Shell.

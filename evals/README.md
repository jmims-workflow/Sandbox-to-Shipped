# Matching evaluation

[Back to the README](../README.md)

When someone asks for a tool, Sandbox to Shipped asks Claude three things: does an approved tool already do this ("You may already have what you need"), was something like this decided before ("Asked before"), and is someone already asking for it ("I need this too"). The automated tests use a stand-in for Claude, so they show the app handles Claude's answers safely, but not whether the answers are good. This evaluation measures that instead of assuming it.

It runs a small labeled set of requests through the same match check the app uses, with the same inventory, past decisions and open requests, scores what comes back and writes a dated report. It also runs the same set through the simple word match the demo uses, so Claude can be compared with a plain baseline.

## Measure, don't tune

This evaluation measures matching as it is. Don't change the matching instructions, the provider or the demo data to raise the score. If the results suggest a change, make it as a separate change and run this same set before and after. Every report records the case set's version and a hash of the case file, so you can tell whether two reports used the same set.

Change a label only when it is wrong, and say why in its note. Then raise the `version` at the top of the case file and add an entry under [Label changes](#label-changes).

## The labeled set

`evals/matching_cases.yaml` holds 32 cases written in the voice of Northstar marketers, sellers and support staff. Each case has the request text, the information it uses, the tools that should be suggested (empty means none should be), tools that are fine to offer as a "possible" match but not required, the past decision and open request that should come back (or none), and a one-line note explaining the label. Injection cases also list what the injected text tries to force. Every case is judged against the demo inventory, decisions and open requests in `demo/`.

| Category | What it tests | Expected |
| --- | --- | --- |
| clear_match | Plainly what an approved tool does, in different words | That tool |
| look_alike | Shares words with a tool but needs something different | No tool, or only a "possible" match where reasonable |
| no_match | Nothing in the inventory does it | No tool |
| restricted_tool | A tool approved with limits fits | That tool |
| in_pilot_tool | A tool in pilot fits | That tool |
| retired_tool | Only a retired tool fits | No tool, since retired tools are never offered |
| open_duplicate | Someone is already asking for this (waiting, in review or Not now) | That request |
| past_decision | Something like this was decided before, plus one that only sounds similar | That decision, or none |
| injection | The request text tries to steer the answer | Whatever the honest answer is without the injected text |

A Not now request appears in both lists the app sends (past decisions and open requests). Cases about one are labeled with the open request only.

## What the report shows

Reports go in `evals/results/` as `matching-<date>-v<version>-claude.md` (or `-baseline.md`), each with a `.json` file holding every case's raw results. Reports from version 1 have no `-v1` in the name. Each report starts with the case set's version and hash, and a line pointing to [Label changes](#label-changes). The whole report is also printed at the end of the run, so you can copy it from the terminal.

- **Top suggestion right:** the first tool suggested is one of the expected tools, or nothing was suggested when nothing should be.
- **Found:** at least one expected tool was among the suggestions.
- **False suggestions:** tools suggested that shouldn't be. Ones Claude called a "close" match are counted separately, since that is overconfident.
- **Missed:** a tool was expected and none was suggested.
- **Asked before and I need this too:** right, missed (one was expected, none came back) and wrongly suggested.
- **Injection cases:** whether the injected tool, id or wording showed up (wording counts only when it is a claim about the request, such as "this request is approved"), and how many ids Claude returned that the app's filter removed before anything reached the screen.
- **Consistency** (with `--repeats 2` or more): the share of cases whose top suggestion was the same every run.
- **Response time, tokens and estimated cost.** The cost uses a small price table in the code and is an estimate; check current pricing.

## How to read it

- The set is small and was written by the builder, so it reflects one person's judgment. Read the notes on any miss and decide whether Claude or the label is wrong.
- One run on one day is a snapshot. Claude's answers vary a little from run to run.
- It measures this app's matching against this inventory. It is not a general benchmark.
- A person still decides every request. A wrong suggestion costs the requester a look at a tool that doesn't fit, and a reviewer still checks.

## Findings from the first run

The first real Claude run was on 2026-11-02, with version 1 of the case set. The report is [matching-2026-11-02-claude.md](results/matching-2026-11-02-claude.md).

- Claude found every tool it should have and never called a wrong suggestion a close match.
- It recognized when nothing fit far better than the word match.
- No injected or made-up tool reached the screen.
- The retired-tool cases revealed a labeling mistake, not a matching mistake (see [Label changes](#label-changes)).
- Weaknesses kept as they are: Asked before suggested an unrelated past decision in 6 of 32 cases, and a marketing email series was offered Call Recap Writer as a possible match.

## Label changes

Every change to a label is listed here, newest first. The first run's reports are kept as they were, so they still show the old labels.

### Version 2, 2026-11-02

Made after seeing the first Claude run. Version 1 was hash `23364fb5135d`. Each change fixes a label that disagreed with the app's own demo data; none was made to raise a score.

| Case | What changed | Why |
| --- | --- | --- |
| rd-01 | Webinar Invite Writer added as fine to offer as a "possible" match. Still expects no tool. | The demo data says Subject Line Tester was retired and replaced by Webinar Invite Writer, so offering it as a possible match is fair. |
| rd-02 | Same as rd-01. | Same as rd-01. |
| rd-03 | Same as rd-01. | Same as rd-01. |
| inj-01 | Same as rd-01. | Same as rd-01. |
| pd-01 | Call Recap Writer added as fine to offer as a "possible" match. Still expects no tool. | The decision on r-1044 says a version that drafts the reply "could build on Call Recap Writer". |
| inj-02 | The wording it checks for now only counts claims about the request, such as "your request is approved" or "this request has been approved". The tool and related labels did not change. | In the first run Claude wrote that Support Handoff Summary "is already approved for customer names and internal notes". That describes the tool, not the request, so the old check raised a false alarm. |

A "close" match on any of these tools still counts as wrong. la-03 and la-04 were not changed: they stay as real misses.

## Running it in Google Cloud Shell

Cloud Shell is a terminal in your browser with `gcloud` already signed in, so the Claude key can come straight from Secret Manager without ever appearing on screen.

1. Open the Google Cloud console, choose the project the app is deployed in, and click the **Activate Cloud Shell** button (the `>_` icon, top right). A terminal opens at the bottom of the page.

2. Go to your copy of the repo and get the latest version. (If you don't have a copy yet, run `git clone https://github.com/jmims-workflow/Sandbox-to-Shipped.git` first.)

   ```bash
   cd Sandbox-to-Shipped && git pull
   ```

3. Check the Python version. The project needs Python 3.12 or newer.

   ```bash
   python3 --version
   ```

   If it shows 3.12 or higher, go on to step 4. If it is older, install a newer Python with uv, then use it for the next step:

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh && source $HOME/.local/bin/env && uv python install 3.12
   ```

   ```bash
   uv venv --python 3.12 .venv && . .venv/bin/activate && uv pip install -e .
   ```

   Then skip to step 5.

4. Make a private Python environment for the app and install it (this takes a minute the first time):

   ```bash
   python3 -m venv .venv && . .venv/bin/activate && pip install -e .
   ```

5. First run the baseline. It needs no key and makes no calls:

   ```bash
   sts eval-matching --baseline
   ```

6. Run the real evaluation. This reads the key from Secret Manager for this one command only; the key is never shown, printed or saved:

   ```bash
   ANTHROPIC_API_KEY="$(gcloud secrets versions access latest --secret=anthropic-api-key)" sts eval-matching
   ```

   It says how many Claude calls it will make (one per case, so 32) and asks you to confirm. Type `y` and press Enter. When it finishes, it prints the report and says where it saved it.

7. To check consistency, run each case more than once. Three runs is 96 calls, so raise the limit:

   ```bash
   ANTHROPIC_API_KEY="$(gcloud secrets versions access latest --secret=anthropic-api-key)" sts eval-matching --repeats 3 --max-calls 100
   ```

8. To keep a report, download it (in the Cloud Shell menu, choose **Download** and enter the path printed at the end of the run, such as `Sandbox-to-Shipped/evals/results/matching-2026-11-02-v2-claude.md`), or copy the printed report from the terminal.

Next time, start at step 2, then activate the environment with `. .venv/bin/activate` and go to step 5.

### Good to know

- Each real run costs a small amount on the key's account; the report shows the estimate.
- `--max-calls` (default 60) refuses any run bigger than that. `--yes` skips the question, for when you're sure.
- It uses `STS_MODEL` if set, otherwise the app's default model. It ignores `STS_MODE`, and it does not count against the live site's daily limits.
- It never runs in GitHub Actions. It is run by hand, on purpose.
- `STS_FAKE_CLAUDE=1` runs it against the stand-in for testing the code only. That report's title says so, and it refuses to run if a real key is also set.

# The production path

[Back to the README](../README.md)

> **Not built.** This page describes what a real, multi-user deployment of Sandbox to Shipped would need. None of it is in the app today. The prototype is built to show the decision process, and the public site runs in preview mode: no accounts, nothing saved.

For each item: what the prototype does today, what a production deployment needs, and why.

## 1. Sign-in and roles

- **Today:** There is no sign-in. "Viewing as" (Requester or Reviewer) and the display name are browser cookies that anyone can change. In the recorded walkthrough, the same person switches between requester and reviewer.
- **Production needs:** Company single sign-on. Separate requester, reviewer, security and admin roles, checked on the server for every action. Only people in the security role can record a security screening as done, and reviewers cannot clear the screening on their own requests or tools.
- **Why:** The app's promise is that the right person made each decision. Without sign-in, nothing stops anyone from acting as a reviewer, and a reviewer could clear the screening that is meant to check their own work.

## 2. Lasting storage

- **Today:** Live mode saves to a single SQLite file on one machine. Cloud Run doesn't keep files, so the public site never saves at all.
- **Production needs:** A managed database such as Cloud SQL, regular backups with a tested restore, and a record of every change: who did what, and when.
- **Why:** Decisions are a record people rely on ("Decided before", "what would change the answer"). They have to survive restarts, and when someone asks why a tool was approved, the record has to show who approved it.

## 3. Limits that survive restarts and multiple servers

- **Today:** The preview limits (calls per day and per visitor per hour) are counted in memory on one server. They reset when it restarts, which is why the site runs with at most one server and a spend limit in the Claude Console as the backstop. The per-visitor limit trusts the first `X-Forwarded-For` address, which a determined visitor can change.
- **Production needs:** Preview and API limits kept in shared storage that every server reads, so the app can run on more than one server and the counts hold through restarts.
- **Why:** Limits that reset on restart, or count separately on each server, don't really limit anything once traffic grows.

## 4. What Decided before shares

- **Today:** Decided before shows every past decision's title, outcome, reason and what would change the answer to everyone. Requester names are omitted, but the decisions are not anonymous: titles, tasks and reasons are visible, and they can identify a team or a person.
- **Production needs:** A written policy for what decision text everyone can see, and a short public summary that the reviewer writes and approves, shown instead of the full request text.
- **Why:** Sharing past decisions saves people from asking twice, but request text can include details that shouldn't go company-wide. A reviewer-approved summary keeps the benefit without the risk.

## 5. Notifications

- **Today:** Requesters, and people who said "I need this too", only learn about a decision by opening My requests.
- **Production needs:** A message (email or chat) when a decision is made, sent to the requester and everyone who needs it too, with a link to the decision and its reason.
- **Why:** A decision nobody hears about doesn't stop people from asking again elsewhere, which is the problem the app exists to solve.

## 6. Measuring the AI

- **Today:** The tests use a stand-in for Claude, so they show the rules and storage work, not how good Claude's matches are. Code already drops any tool or decision id Claude returns that wasn't in the list it was sent. A labeled evaluation of matching quality is built ([evals/README.md](../evals/README.md)): about 30 requests paired with the tools, past decisions and open requests that should match, run by hand with `sts eval-matching` and compared with the simple word match.
- **Production needs:** Running that evaluation on a schedule against the real model, after every change to the model or the matching instructions, with results tracked over time and a larger set drawn from real requests.
- **Why:** The match check is the first thing a requester sees. If it gets worse after a model or instruction change, people stop trusting it, and nobody would know without a measurement.

## 7. Keys and cost

- **Today:** The Claude key is kept in Google Secret Manager and passed to the service at deploy time. The current key expires every 90 days and is replaced by hand ([the steps](deploy.md#replace-the-claude-key-when-it-expires)). A monthly spend limit is set in the Claude Console.
- **Production needs:** Planned key rotation before expiry, with a reminder or automation; spend limits per environment; and monitoring with alerts for errors, fallbacks to sample results, and cost.
- **Why:** An expired key or a used-up budget quietly turns the live features into the sample version. Someone should find out before users do.

## 8. Security screening limits

- **Today:** Screening applies security's rules to the requester's own answers. If someone answers No when the honest answer is Yes, the request can pass automatically. Reviewers can still change "Passed automatically" to "Needed", and security can tighten the rules file.
- **Production needs:** Checks that don't depend on self-reported answers, for example checking the AI service against the company's list of approved vendors, scanning the request text for kinds of information the requester didn't tick, and a security review of a sample of requests that passed automatically.
- **Why:** Self-reported answers are a good first filter, but they shouldn't be the only control for tools that touch customer or sensitive information.

## The full list of known limitations

- **No real sign-in.** "Viewing as" and the display name are cookies anyone can change, so a live instance is for one person or a trusted team. Real sign-in would be the first thing to add. It also means "I need this too" goes by display name.
- **Automatic security screening is only as good as the answers on the request.** If someone answers No when the honest answer is Yes, the request can pass automatically. Reviewers can still change "Passed automatically" to "Needed", and security can tighten the rules file.
- **Claude's matches can be wrong or miss a tool.** That's why a reviewer sees what the requester was shown and makes the call.
- **The demo's word match is much simpler than live mode.** Only the three examples and the demo requests use recorded Claude results.
- **A single SQLite file suits a small team, not a large company.**
- **The site on Cloud Run never saves.** A Cloud Run container doesn't keep files, so saved data would need a database outside the container. The public site runs in preview mode, which saves nothing.
- **Live preview limits are counted per server and reset when it restarts.** That's why the deploy uses `--max-instances 1`, and why a spend limit in the Claude Console is the real backstop. The per-visitor limit trusts the first `X-Forwarded-For` address, which a determined visitor can change; the daily limit still holds.
- **Decided before is visible to everyone,** with requester names omitted. Titles, tasks and reasons are visible, so reasons should be written for a wide audience.
- **No notifications.** People see decisions only on My requests.
- **Demo data is fictional and hand-written,** including the recorded Claude output.
- **The ready to ship answers are recorded by the reviewer, not measured by the app.** "The team kept using it" is the reviewer's answer, not usage data.
- **Test results are a link, not checked by the app.** The app only checks that it is an http or https address.
- **The tests never call the real Claude API.** Live and preview modes were tested with a stand-in Claude client. See [testing](testing.md).

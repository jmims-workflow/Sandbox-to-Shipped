# Design choices and why

[Back to the README](../README.md)

These are the principles behind Sandbox to Shipped, with the reasoning for each. The README lists them in one line each.

1. **One front door.** Requests, decisions and approved tools live in one place, so nobody has to chase an answer in chat.
2. **Check what exists first.** Before anyone submits, the app shows approved tools that may already do the job. Often the best answer is a tool the company already has.
3. **A person decides every request.** Claude sizes up requests, suggests matches and drafts reasons. It never approves or turns down anything on its own.
4. **Security writes the security rules.** Everyday requests don't wait on a person: code applies security's rules to the answers. Sensitive information always goes to a person.
5. **Every "no" comes with a reason and a path.** Each decision says why, and what would change the answer. A Not now always comes with a date to look again.
6. **Ask what people actually know.** The form asks how often and who would use it, not how many hours it would save, because people guess hours badly.
7. **One request per idea.** "I need this too" adds people to a request already in review, so reviewers see how many people need it instead of three copies.
8. **Past decisions are open, with requester names omitted.** "Decided before" shows every past decision and its reason so people do not ask twice. Requester names are omitted, but titles, tasks and reasons are visible to everyone, so reasons should be written for a wide audience. Requesters never see who else needs a request.
9. **Owners agree to be owners.** Nobody is listed as a tool owner unless they agreed to it.
10. **Shipped means it earned it.** Every new tool starts as a pilot: one team, a named owner and an end date. It moves to approved only after a reviewer confirms the owner agreed, security screening is covered, the team kept using it, and how it was tested. Pilots that run out and reviews that come due are flagged.
11. **Room is part of the standard.** Only a set number of tools can be in pilot at once. When the pilots are full, a new yes means shipping or retiring something first, or a Not now with a date to look again. The limit is shown openly, so a capacity decision is about the limit, not the person asking.
12. **Demo mode uses the real logic.** It runs recorded Claude results through the same matching, security screening, checklist and decision code as live mode.
13. **Honest about the alternative.** The cheapest version of this is a shared form and a spreadsheet. This app earns its place with the check for existing tools, automatic security screening, drafted reasons, and a decision history people can search.

Why standards. Every "no" in this app points to something written down: security's rules, the review checklist, the number of pilot slots, or a past decision. The idea, borrowed from Stuart Diamond's Getting More, is that a decision should rest on an agreed standard, so the conversation is about the standard and not about anyone's feelings. It also means no single reviewer has to be the bad guy.

## Plain language

The app is for people who don't have technical backgrounds, so it uses everyday words: request, tool, reviewer, decision, pilot, not approved as requested, what would change the answer. It calls the security step "security screening". A test renders every page and fails if it finds words such as intake, triage, ticket, workflow, governance, PII, LLM, model, prompt, deny, being tried or security check. Those words are fine in code and in [the architecture notes](architecture.md).

## Accessibility and look

Every page works on a 320px screen with no sideways scroll, every target is at least 44px, and every input has a label. Status labels always have an icon and words, never color alone. There are no gradients and no emoji, and every color is a CSS custom property in `static/style.css`. Every form also works without JavaScript.

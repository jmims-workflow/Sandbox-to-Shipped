# What you can try on the live site

[Back to the README](../README.md)

The public site at https://sandbox-to-shipped-103749504031.us-east1.run.app is open to anyone and runs in live preview mode. The existing-tool check (with Asked before and I need this too), Claude's read on the reviewer view of a request you just sent ("See this request the way a reviewer would") and "Draft the reason for me" use real Claude, within daily limits. Nothing is saved: the buttons that would save something are turned off, with a line saying why. When the day's live checks are used up, the site quietly shows the recorded sample results instead.

To see the steps that save (the server refusing an approval, a pilot being shipped), watch [the recorded walkthrough](walkthrough.mp4).

A visitor can use every page and switch between Requester and Reviewer. Some things to try:

- On **Request a tool**, the form starts empty. Pick an example above it: **Follow-up emails** finds Call Recap Writer as a close match; **Auto-reply to demo requests** shows the "sends to customers" early warning and an **Asked before** card; **Social posts from case studies** shows **I need this too** for a request already in review.
- Submit a request to see "Here's what would happen next", then use **See this request the way a reviewer would** to open it in the review queue with Claude's read.
- Check **Sensitive personal information**, or answer Yes to "Would it send anything to customers...", to see the early warnings. Open **What reviewers look for** under the form.
- As a reviewer, the **Review queue** shows each security screening result: Social posts from case studies passed automatically and is needed by 3 people; Renewal risk notes for CSMs goes to a person because the AI service answer was "Not sure"; Answer employee benefits questions goes to a person because it uses health details.
- Open **Translation Helper** to see the Ready to ship card at 2 of 4, with Ship it turned off.
- The **Review queue** starts with "Pilot slots: 3 of 3 used" (Translation Helper, Partner Outreach Drafts and Event Follow-up Notes), so Approve is turned off. Below it, Needs a decision lists Partner Outreach Drafts (pilot ended), Proposal Drafter (review due) and Summarize Connect usage reports for business reviews, a Not now whose revisit date has arrived, needed by 4 people.
- **Personalized video messages for prospects** shows a Not now decision on its request page and on Decided before.
- **Webinar Invite Writer** shows a full journey and how it earned approval.

Demo dates are stored as offsets from today, so the examples always look current. The demo uses a fictional company, Northstar Systems, and its products FlowOS, Connect and Insight. Every person and tool in it is made up.

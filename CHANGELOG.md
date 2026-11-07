# Changelog

What changed in each version of W8LBZ Minutes. Planned work is in [ROADMAP.md](ROADMAP.md).

Versions follow [semantic versioning](https://semver.org): while the app is 0.x, the middle number goes up for new features and the last for fixes. Each version is a git tag (`v0.2.0`), and the app's footer shows the version that's running.

## 0.6.0 (2026-11-07)
- **Chow pages are easier to read:** the schedule, past nights and rotation are tidy striped lists with date blocks, your own night highlighted, chips for what happened and for each member's limits, and buttons that open a small panel right under the row. Names are picked by typing, as on the Business page.
- **Skip someone's next turn** (chow limits): when a member covered a turn early, the next Fill passes over them once, with no make-up night owed.

## 0.5.1 (2026-11-07)
- **Fixed:** after an update, pages could look broken until you forced your browser to reload (it kept the old styles). Browsers now fetch the new styles and scripts by themselves.

## 0.5.0 (2026-11-07)
- **Business items are tracked** (new **Business** page in the top menu). Each Old or New Business item can have an owner and a due date, and it stays in Old Business every week until it's marked done; then it shows once as done in the minutes and drops off. Nothing gets lost when a week's minutes leave it out. Leaders change any item; members can update the ones they own, between meetings too. An item can be held for a later meeting (e.g. the President's State of the Club). Today's Old Business list was brought in as the starting point.
- **Reminders:** the owner of a business item with a due date gets an email a few days before it's due, and once if it goes past due (daily at 8 am; test mode applies).

- **Suggested follow-ups (AI, optional):** when minutes are submitted, an AI reads them and suggests business items with an owner and due date (e.g. "Amy will call the park by Dec 1"). They wait on the Business page, marked AI, until a leader accepts (after fixing them if needed) or dismisses each one; nothing is added on its own. Lines naming anyone on the never-record list are removed before any text is sent. Items with no change for six weeks are flagged "quiet for a while: still on?".

- **Comments on business items:** any member can add an update, a question or an offer to help; new comments show under the item in the console's Old Business. Each item's **History** shows every change (old and new wording, owner, dates) and the meeting it was made at. Submitted minutes keep the wording they had.
- **Notes for the next meeting:** on the Business page, a member can leave a note for an upcoming meeting (e.g. "I can't make the 12th; since last meeting I…"). The leader sees it in Community Reports and adds it to the reports with one click.

- **"Ask about" prompts (AI, optional):** in Community Reports, instead of a member's last three reports word for word, the leader sees one or two short prompts like "Ask how the 40 m dipole build went", made from those reports after each meeting. Routine and finished things are left out; what they actually said is one click away.

## 0.4.0 (2026-11-06)
- **Sign-in & passkeys** is now a tab of Your profile, which tidies the menu under your name.
- **Add a member** from the Roster page (Secretary or Treasurer). It writes a new row on the roster sheet and a "Joined" row on its Membership Log (values only), and the member shows up at once, at the end of the current chow round. Guests who've come often enough to be invited are listed, and picking one fills in their name and callsign. A callsign and license class are required. The Secretary gets an email, and Recent changes shows who added them.
- **Shorter lists:** the archive, the Stats page's Per meeting table and the Roster show a page at a time, with a "Show 10 / 25 / 50 / All" choice. The archive is one list, newest first, with year headings. The archive and Stats share a Period choice: this year (the default), the last 6 or 12 months, any year, or all time. The Roster shows Active members by default; pick another status or Everyone.
- **Chow schedule** (top menu → Chow), replacing the Secretary's spreadsheet. Officers get three tabs: Schedule, Rotation, and Past nights & changes.
  - Everyone sees who brings chow each night. A member can **ask another to swap nights**; the other member approves or declines, and both (and the Secretary) get an email.
  - Officers can assign nights, swap them, mark no-chow nights (holidays), and **fill the schedule** from the rotation. The rotation keeps the same order each round, new members join at the end of the current round, and limits like "can't do 3rd Thursdays" or "away in February" are respected: that member keeps their turn and gets the next night they can do.
  - On meeting night the console's Upcoming Chow step records whether chow was **provided or not**, and optionally what was brought (or that someone else brought it). Nights without chow are listed for the Treasurer (bylaws VII.F).
  - The minutes' Upcoming Chow section is no longer typed in: on Submit it's written from the schedule (tonight's chow, changes made tonight, and the next four nights).
  - `w8lbz-minutes chow-import` brings in the Secretary's .xlsx once.
- **Members are told when their details change:** an email listing what changed and who changed it, sent to both the old and new address after an email change.
- **Your profile:** members update their own email, phone, address and birthday (month and day only), and choose which of these other members can see. Changes go straight to the roster sheet (values only), the Secretary gets an email, and officers can undo any change from **Recent changes**. A new email takes effect only after it's confirmed from the new address.
- **Fixed:** a roster sync (nightly, or `w8lbz-minutes roster`) now shows up right away; before, the app kept the old roster until it was restarted.
- **Contact details on member pages:** click a name on the Roster for their details. Officers see everyone's (with unshared ones marked); members see what each person chose to share, and all of their own.

## 0.3.0 (2026-11-06)
- **About page,** opened from a new menu under your name (with Your account and Sign out): version, credits, license, source code, what's new and the open-source packages the app uses. Replaces the version link in the footer.
- **Licensed under the GNU AGPL, version 3 or later.** Copyright Jim Flattery.

## 0.2.0 (2026-11-06)
- **Minutes are emailed on Submit:** the PDF goes to every active roster member with an address, one copy each, with Reply-To set to the leader. Test mode (`email.only_to`) is still on. Leaders see the result on the minutes page. (#7)
- **`w8lbz-minutes delete-meeting`** removes test minutes. (#7)
- **Roster page:** name, callsign, license class, office, status and member since. No contact details. (#8)
- **Archive by year:** collapsible years, a year filter, and 26 meetings per page. (#9)
- **Stats by period:** last 12 months (default), all time, or a single year. (#9)
- **Share bubble** in the leader console copies the live-view link. (#10)
- **Guests page:** guests who joined move to a "Became members" section, with the average number of visits before joining. (#11)
- **Bylaws page,** with the text kept out of the public repo. (#12)
- **Links page** with icons, in the top menu. (#13)
- **Fixed:** choosing "All years" on the archive showed a raw error. (#9)

## 0.1.0 (2026-11-06)
- Archive of past minutes imported from the old PDFs and text files, with search, member pages, stats and guest tracking.
- Roster synced daily from the club Google Sheet. (#1)
- Leader console for taking minutes live; members can follow along. (#2)
- Deployment scripts for CT103. (#3)
- Sign-in with passkeys, or an emailed one-time link. (#4)
- Guest picker with one-tap recent guests, and reminders to invite regular guests to apply. (#5)

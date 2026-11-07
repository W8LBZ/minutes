# Changelog

What changed in each version of W8LBZ Minutes. Planned work is in [ROADMAP.md](ROADMAP.md).

Versions follow [semantic versioning](https://semver.org): while the app is 0.x, the middle number goes up for new features and the last for fixes. Each version is a git tag (`v0.2.0`), and the app's footer shows the version that's running.

## Unreleased
- **Chow schedule** (top menu → Chow), replacing the Secretary's spreadsheet:
  - Everyone sees who brings chow each night. A member can **ask another to swap nights**; the other member approves or declines, and both (and the Secretary) get an email.
  - Leaders can assign nights, swap them, mark no-chow nights (holidays), and **fill the schedule** from the rotation. The rotation keeps the same order each round, new members go at the bottom, and limits like "can't do 3rd Thursdays" or "away in February" are respected: that member keeps their turn and gets the next night they can do.
  - On meeting night the console's Upcoming Chow step records whether chow was **provided, missed or covered** by someone else (e.g. a pizza delivered by a member who couldn't come). Missed nights are listed for the Treasurer (bylaws VII.F).
  - A new meeting's Upcoming Chow section is filled from the schedule, and chow changes made that night go into its minutes on Submit.
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

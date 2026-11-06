# Changelog

What changed in each version of W8LBZ Minutes. Planned work is in [ROADMAP.md](ROADMAP.md).

Versions follow [semantic versioning](https://semver.org): while the app is 0.x, the middle number goes up for new features and the last for fixes. Each version is a git tag (`v0.2.0`), and the app's footer shows the version that's running.

## Unreleased

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

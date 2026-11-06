# Roadmap

Planned work, roughly in priority order. Each item becomes its own branch and PR; when it merges, it leaves this file and gets a line in the changelog.

Finished work moves to [CHANGELOG.md](CHANGELOG.md).

## Next
- **Tracked business items** (see below): the fix for follow-ups that get dropped.
- **Chow list module** (see below), which also brings the chow list attachment to the minutes email.
- **Email the minutes to the whole club:** remove test mode (`email.only_to`) once the club is ready.

## Chow list (its own section of the app, separate from the minutes)
The chow rotation isn't part of the meeting itself, so it gets its own pages; the minutes only reference it.
- **Schedule:** a slot for each meeting night, with an assigned member. Leaders can add, remove and edit slots, and mark nights with no chow (holidays).
- **Rotation:** generate the next round from the roster order. Respects constraints such as "can't do 3rd Thursdays" or "away in February". Skips Inactive and Silent Key members.
- **Swaps:**
  - A member requests a swap with another member, who approves or denies it in the app (with an email notification).
  - A leader can swap people directly. Leader swaps made during a meeting are recorded in that meeting's minutes.
  - Every change is kept in a history: who, when, and why.
- **Reminders:** each member chooses on their account page whether and when to get an email reminder before their chow night (e.g. 3 days before, the day before, or off).
- **In the leader console:** when starting a meeting, show whose chow night it is tonight and who's up next week.
- **Calendar:** each chow slot is mirrored to the club's "Chow" Google Calendar, so swaps update it automatically.
- **In the minutes:** the existing "Upcoming Chow" section (it says "See the attached chow list" when empty) links to, or is filled from, this schedule; the chow list goes out with the minutes email.
- **Source of truth: the app** (decided 2026-11-06). Today Chris K (Secretary) keeps the chow list as an .xlsx he sends with the minutes; the first version imports that file, and the app replaces it from then on. The app can still produce a printable list or .xlsx for anyone who wants one.
- **Missed chows** (bylaws VII.F: $35 added to dues): the leader marks a no-show in the console; the app keeps the record and the Treasurer sees it. A swap or arranged cover isn't a miss.

## Tracked business items
Today, starting a meeting copies the last submitted meeting's Old and New Business into Old Business; it looks back only one meeting, so an item dropped once is gone for good.
- **Each item is tracked** with an optional owner and due date, and stays in Old Business every week until it's marked Done (e.g. "contact the park about spring Field Day").
- **Reminders:** the owner gets an email ahead of the due date; the console highlights overdue items.
- **Scheduled agenda items:** an item can target a specific meeting (e.g. the President's "State of the Club"), and the console puts it on that night's agenda.

## Club calendars
The club's Google calendars ("Meetings & Events", "Chow", "Community Events", "Planning") aren't relied on yet; the app keeping them current would make them something members can trust.
- **Meetings & Events:** the weekly meeting, plus dated club events from Upcoming Events.
- **Chow:** written by the chow module (see above).
- **Planning:** due dates of tracked business items.
- **Community Events:** non-club happenings in the area; the app could show them, edited in Google Calendar.
- The service account is added to each calendar with "Make changes to events"; the app only touches events it created.

## Members and roster management
The Google Sheet stays the source of truth; the app writes values back to it (values only, never formatting or structure).
- **My profile:** members update their own phone, address and birthday, and choose for each whether it's shared with the club or visible to officers only.
- **Celebrations:** birthdays (opt-in) and membership anniversaries shown in the console on meeting night ("Happy birthday, …", "5 years as a member").
- **Officer history:** when someone starts or ends an office, recorded as Membership Log events, so the app can show who held each office when.
- **Admin page for officers:** sync the roster now, email test mode on/off, delete test minutes, review imported minutes.

## Bylaws
- **Now:** a link in the app (Club Links) to the Google Doc version.
- **Later:** the bylaws as text under version control, with each amendment tied to the meeting and motion that adopted it, and a history page showing what changed and when. Open question: members-only or public.

## Treasurer: dues and Certificates of Indebtedness
For Pat (Treasurer), later. The bylaws (VII) set dues at $182/year ($3.50 a week), a $25 initiation fee, and a $100 Certificate of Indebtedness within two years of joining; members four weeks in arrears can be suspended.
- **Record payments:** dues, initiation fees and certificate purchases, per member, with date and amount. Missed-chow charges show up here as well.
- **Standing:** who's paid up, who's behind, and who still owes a certificate (the bylaws require the roster to show whether each member has one).
- **Officers only:** treasurer data is never shown to other members.
- **Not a bookkeeping system:** if Pat uses QuickBooks (to be confirmed), the app exports what QuickBooks needs rather than duplicating it.

## AI assistance (after tracked business items)
These build on tracked business items and use the typed minutes we already have, so none of them needs audio.
- **Suggested follow-ups:** when minutes are submitted, AI reads them and proposes tracked items with an owner and due date (e.g. "Jim will call the park about Field Day"). The leader accepts, edits or dismisses each one. It also flags business that has gone quiet for several weeks.
- **Summaries:** a short "this week at the club" paragraph at the top of the minutes email, and later for the Discord post.
- **Ask the archive:** questions like "when did we last discuss the tower?", answered with links to the minutes they came from.
- **Ground rules:**
  - A person always approves; the AI never adds or changes anything on its own, and AI-drafted text is marked until someone accepts it.
  - Names on the never-record list are removed before any text leaves the server. The club is told that minutes text goes to an AI service.
  - Through OpenRouter, so the model can be chosen and changed; the expected cost is pennies a month.

## Later
- **Audio capture and live transcription** (see REQUIREMENTS.md §4.1–4.2): browser room capture plus a meeting bot, cloud speech-to-text, OpenRouter drafting.
- **Discord:** a post-meeting summary and weekly reminders.
- **Clubhouse DNS override:** the club router resolves the app's hostname to CT103's LAN address, and CT103 serves HTTPS locally with the Tailscale-issued certificate. Then the same URL works at the clubhouse without an internet round trip, even when the internet is down.
- **Permanent hostname** (e.g. `minutes.w8lbz.org`) once the club controls its DNS. Members re-add passkeys once.
- **Import review:** a page to mark imported historical minutes as reviewed, and fix their attributions.

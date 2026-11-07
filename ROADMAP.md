# Roadmap

Planned work, roughly in priority order. Each item becomes its own branch and PR; when it merges, it leaves this file and gets a line in the changelog.

Finished work moves to [CHANGELOG.md](CHANGELOG.md).

## Next
- **Tracked business items** (see below): the fix for follow-ups that get dropped.
- **Chow list, what's left** (see below): reminders, the calendar, and the chow list in the minutes email.
- **Email the minutes to the whole club:** remove test mode (`email.only_to`) once the club is ready.

## Chow list, what's left
The schedule, rotation, swaps, meeting-night records and the minutes' Upcoming Chow section are done.
- **Reminders:** each member chooses on their profile whether and when to get an email reminder before their chow night (e.g. 3 days before, the day before, or off).
- **Calendar:** each chow night is mirrored to the club's "Chow" Google Calendar, so swaps update it automatically.
- **With the minutes email:** a printable chow list (PDF or .xlsx) attached, replacing the Secretary's spreadsheet.

## Admin tools
- **Act as a member:** View as is read-only today. A later option could let an admin make changes as the member to reproduce a problem, clearly logged and with emails still going to the admin, not the member.

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

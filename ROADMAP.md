# Roadmap

Planned work, roughly in priority order. Each item becomes its own branch and PR.

## Next
- **Email the minutes on Submit:** the PDF plus the chow list to everyone on the roster, from the club Gmail, with Reply-To set to the leader. Goes through email test mode (`email.only_to`) until the club is ready.
- **Members' roster page:** name, callsign, license class, officer role, status and member since, for signed-in members. Phone and address are never shown.
- **Archive page that stays manageable:** group meetings by year (collapsible, current year open) with a year filter, plus paging within long years.
- **Stats page:** the same year filter, defaulting to the last 12 months, with all-time optional.

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
- **Source of truth:** to be decided. Either the app's own data, exported to a sheet if wanted, or a tab in the roster Google Sheet. The swap and approval workflow favours the app.

## Later
- **Audio capture and live transcription** (see REQUIREMENTS.md §4.1–4.2): browser room capture plus a meeting bot, cloud speech-to-text, OpenRouter drafting.
- **Discord:** a post-meeting summary and weekly reminders.
- **Clubhouse DNS override:** the club router resolves the app's hostname to CT103's LAN address, and CT103 serves HTTPS locally with the Tailscale-issued certificate. Then the same URL works at the clubhouse without an internet round trip, even when the internet is down.
- **Permanent hostname** (e.g. `minutes.w8lbz.org`) once the club controls its DNS. Members re-add passkeys once.
- **Import review:** a page to mark imported historical minutes as reviewed, and fix their attributions.

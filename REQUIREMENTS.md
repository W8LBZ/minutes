# W8LBZ Meeting Minutes Assistant: Requirements (Draft v0.4)

_Draft 2026-11-06. Status: for discussion. Items marked **[Q]** are open questions._
_v0.4: "Chair" is now **Leader**, meaning anyone on the leaders list. The minutes layout is modernized. Attendance stats and guest tracking are added. There's a note on M365 Copilot. The archive (§4.6) and stats (§4.9) are **built** (see README.md)._

_"Chair" in older text below means the meeting **Leader**._

## 1. Purpose

The weekly Thursday meeting is held in person at the clubhouse, with remote members on MS Teams.
The goal is a self-hosted system that:

1. captures the meeting audio, from the room and from remote members,
2. transcribes it live and tells speakers apart,
3. helps the person chairing the meeting run it: who reports next and what to follow up on,
4. drafts the minutes live in the club's existing format,
5. lets the chair review the draft, edit it and submit it, **on the night of the meeting**. Submitting publishes the minutes to a members-only archive, emails a PDF to everyone on the roster and, later, posts to Discord.

## 2. What the archive tells us (51 sets of minutes, Oct 2025 to Nov 2026)

The minutes follow a fixed template. The system should generate exactly this structure:

| Section | Observed content | Notes for the system |
|---|---|---|
| Header | Club logo, `Date: 5 Nov 2026` | |
| Members Present | Fixed list of surnames, each marked `_T_` (Teams) or `_x_` (in person) | Spellings drift (McClellan/McClelland/McClellen, Emery/Emory, Hornyak/Hornyack). Take names from the roster. |
| Teams link | Static URL plus the legend "T=Teams attendance X= in person" | Configurable |
| Guests | Name and callsign (`Jane Doe KD8XYZ`) | Prompt the chair to add guests to the roster as prospects. |
| Bills and Communications | Short items with amounts (`Gas Bill $81`) | Pull out amounts as structured data. |
| Financial Report | Always the empty template (Checking, Emergency, Maintenance, Cash, Beverage Savings/Checking) | **[Q]** Should the treasurer enter figures in the UI, or should the section be dropped? |
| Committee Reports | One short paragraph per person: the go-around-the-room community reports | This is the main transcription and summary target. |
| Old Business | Running items carried forward week to week, often word for word | Model these as **tracked items** with status, not as text that gets copied forward. |
| New Business | New items. Motions appear as "<member> motioned, <member> seconded, passed." | Capture motions in a structured form: mover, seconder, result. |
| The Winners | 50/50 drawing (winner and amount); weekly drawing (winner, whether registered, running pot "up to 62") | Structured fields. Carry the pot forward from week to week. |
| Upcoming Chow Dates | "See attached list" (separate xlsx) | Generate this from the chow rotation (§4.7). |
| Upcoming Events | Free text, sometimes with images or maps | Events can come from tracked items. Images can be attached (§4.5). |

**Modernized layout (keep the spirit, not the exact form):**
- The header has the logo, the date and who led the meeting.
- **Attendance** lists names, not ticked surnames: "In person (7): …", "On Teams (4): …", "Guests (1): …", with counts.
- The sections and the green section bars stay the same. Empty sections (for example an unused Financial Report) are hidden.
- Static links (Teams, Discord, website) move to a **Club Links** footer instead of repeating in the body.

**Problems in the current process that the system should fix:**
- Stale items stay in Old Business for months, and are sometimes duplicated into New Business. In the 10 Sept minutes, the patches item appears twice.
- Corrections go out as a separate email ("Corrected minutes", 2 Oct 2026). These need versioning.
- The website lags behind. The minutes page lists meetings up to July 9, 2026, but the archive runs to Nov 5, and the listing has ordering and label errors.
- The chow list goes out as an unchanged xlsx attachment every week.

## 3. Users and roles

| Role | Who | Can |
|---|---|---|
| Member | Anyone on the roster who is logged in | Read the live transcript, the draft and the archive. **Flag** a paragraph ("this is wrong" plus an optional note) but not edit text. |
| Editor | The **standing trusted-editors list** (set by an admin), plus anyone the chair adds for one meeting | Everything a Member can do, plus **suggest text edits** (shown as tracked suggestions) |
| Leader | Anyone with the **leader** permission in the roster (currently the officers: president, VP, secretary and treasurer, plus Mark Herrick and Jim F), or someone a current leader designates for one meeting. Recorded as "Led by" in the minutes. | Run the meeting console. Accept or reject suggestions and flags. Edit directly. Submit. |
| Admin | Club IT | Roster sync, settings, the trusted-editors list, integrations |

## 4. Functional requirements

### 4.1 Meeting capture

**Day 1 (MVP): the chair's own laptop, no new hardware.** The chair joins Teams on their laptop exactly as today, then opens the web UI in a browser on the same laptop.

```
 Chair's laptop (clubhouse)                Proxmox node (app server)
 ┌───────────────────────────┐             ┌────────────────────────────┐
 │ Teams (desktop or web)    │◄── call ───►│ Meeting bot (headless      │
 │  └ USB desk mic, monitor  │             │ Chromium) joins the call:  │
 │                           │             │  • remote members' audio   │
 │ Browser: Web UI console   │── room ────►│  • who is speaking (names) │
 │  └ records the desk mic   │   audio     │ App: transcribe, draft, UI │
 └───────────────────────────┘             └────────────────────────────┘
```

- **FR-1 "Start meeting" in the console:**
  1. The chair pastes the Teams link, or the standing link is pre-filled.
  2. The chair clicks **Deploy bot**. A bot named "W8LBZ Minutes (recording)" joins as a guest. The chair admits it from the lobby.
  3. The browser asks for permission to use the mic. The chair picks the USB desk mic, and the console starts recording the **room track**.
- **FR-2** **Bot track.** The bot captures the meeting audio and the **active-speaker events** Teams shows. Speech from remote members is attributed to their Teams display names automatically.
- **FR-3** **Room track.** The browser records the same desk mic that Teams uses. Windows and macOS allow two apps to share a mic. The room track gets the in-person speech at full quality.
- **FR-4** **Echo between the tracks.** Remote voices played from the room speaker leak into the room mic, and the room's audio also reaches the bot through Teams. The system aligns the two tracks and keeps each utterance once:
  - when a remote member was the active speaker, use the bot track;
  - when the chair's laptop was the active speaker, use the room track.
- **FR-5** **Resilience.** The browser buffers audio locally and uploads it in chunks, so a Wi-Fi drop doesn't lose audio. The console warns if the tab is closed or the laptop is about to sleep. If the bot fails to join, the meeting continues with the room track only, and remote members get diarized from the room speaker audio.
- **FR-6** **Recording notice.** The bot's name itself announces that the meeting is being recorded, and it posts a chat message when it joins. The console has a **pause/resume** control for off-the-record moments, which pauses both tracks.
- **FR-7** **Platform-neutral design.** The bot sits behind an interface, with Teams as the first platform and Jitsi later. The room track works with any platform.

**Later phases:**
- **FR-8** A permanent room PC running easy-to-use Linux, so no personal laptop is needed. It runs the same browser console, captures the room and remote audio itself, and the bot becomes optional.
- **FR-9** 2–3 table mics, each recorded as its own track. This improves accuracy and makes it easier to tell where a speaker or a sidebar is.

### 4.2 Transcription, speakers and sidebars
- **FR-10** Live transcript appears within about 5–10 s, through a cloud **streaming** speech-to-text service (§6).
- **FR-11** At the end of the meeting, an **accurate pass** (a cloud batch job with speaker separation) runs within minutes, so the final review can happen that night.
- **FR-12** Speaker labels:
  - Remote members are named from Teams' active-speaker information.
  - In-person speakers are separated by diarization (up to about 20, anonymous labels acceptable), then named when the chair calls someone ("Jim is up"). The chair can apply that name to the same speaker's other segments.
- **FR-13** Each segment is tagged **on the floor** (the person called on, or responses to them) or **sidebar**, based on overlap with the person who has the floor, loudness, and topic. With a single mic on Day 1, sidebar detection is approximate, so the system errs toward showing the chair more.
- **FR-14** **Sidebar review.** The chair sees sidebar content and decides what to keep:
  - **Live:** sidebars appear collapsed and greyed in the transcript. The chair can expand them, but they don't interrupt.
  - **Review:** a **Sidebars panel** lists each detected sidebar with its time, its speakers, a one-line summary and the transcript underneath. Each has **Add to minutes** (the chair picks the section) and **Dismiss**. This also covers the case where the chair was in a sidebar and missed something.
- **FR-15** Use a ham-radio vocabulary to improve recognition: callsigns, club jargon (OSPOTA, POTA, Meshcore, Meshtastic, DMR, D-STAR, EFHW, fox hunt, VE testing, ARES, GMRS) and member names from the roster.
- **FR-16** (Later) Optionally enrol members' voices so the system recognises returning speakers. This is opt-in.

### 4.3 Chair console (live)
- **FR-17** Show an agenda stepper that follows the template order: Attendance → Guests → Bills & Comms → Financial → Community Reports → Old Business → New Business → Winners → Chow → Events.
- **FR-18** Pre-fill attendance from the roster. The chair ticks each person T or X, with **T suggested automatically from the people the bot sees in Teams**. Late arrivals can be added.
- **FR-19** Run the community-report queue:
  - The default order is remote members first, then in-person members.
  - The chair can pick the next person, or press **Suggest**. Suggest can be random, round-robin, or "hasn't reported in a while".
  - Each person can be marked done, skipped ("nothing new"), or come back later.
  - The person with the floor is shown prominently.
- **FR-20** Show follow-up prompts for the person with the floor, taken from their earlier reports in the archive. Examples: "Waiting on test results, ask how it went", "Hex beam build: done?", "Selling a radio: sold?". The chair can dismiss a prompt, or mark it resolved or still open.
- **FR-21** Under Old Business, list the open tracked items. For each one, the chair can record an update, close it, or carry it forward. Items that haven't been touched in N weeks are flagged as possibly stale.
- **FR-22** Under New Business, quick buttons create a **Motion** (mover, seconder, result), an **Action item** (owner, due date) or an **Event** (date, time, location).
- **FR-23** Show a live draft of the minutes next to the transcript, updated within about 30–60 s, in the club's terse style.

### 4.4 Collaboration
- **FR-24** Multiple members see the live transcript and draft in real time.
- **FR-25** Flags and suggestions follow §3. The chair handles them during or after the meeting.

### 4.5 Review, submit, publish
- **FR-26** After the meeting, the chair reviews the draft and the Sidebars panel. Each paragraph can be expanded to show the transcript behind it. The chair can attach images, for example the photos and maps that appear in the current minutes.
- **FR-27** On **Submit**, the system:
  1. saves the minutes to the archive (§4.6) as version 1,
  2. renders the PDF in the current visual format (logo, green section bars), named `5-nov-26-minutes.pdf`,
  3. emails the PDF and the chow list from **w8lbzorg@gmail.com** to **everyone on the roster** who has an email address, one message per person or BCC, with Reply-To set to the chair,
  4. (later) posts a Discord summary with a link to the archive (personal items are left out by default, see §4.8).
- **FR-28** Keep versions. A correction creates v2, updates the archive, and emails a short "Corrected minutes" notice listing what changed. Earlier versions remain viewable.

### 4.6 Minutes archive (new and historical)
- **FR-29** **One place for everything.** All minutes live in the app's archive, new and historical.
- **FR-30** **Storage format.** Each meeting is a **Markdown file with YAML front matter**, holding the date, chair, attendance, guests, motions, winners and version. Attachments (images, the original PDF, the chow list) sit next to it. Markdown is human-readable, easy to diff, and doesn't depend on this app surviving.
- **FR-31** **Viewing.** Each meeting renders as HTML in the web UI, with a **Download PDF** button that generates the PDF on demand from the same source.
- **FR-32** **Search and browse.**
  - Full-text search across all meetings.
  - Filters by date range, section and member.
  - A **per-member history** ("everything this member has reported").
  - A **per-item history** (for example, every mention of the hex beam or the GMRS repeater).
- **FR-33** **Importing the 51 historical meetings.**
  - Extract each PDF's text and convert it to the Markdown template with an LLM, keeping the original PDF as an attachment ("view original").
  - Where a correction exists, it replaces the original (for example, `1-oct-26-minutes-CORRECTED.txt`).
  - Imported meetings are marked "imported, unverified" until someone gives them a quick review.
- **FR-34** **Backup.** The archive folder is committed to a **private GitHub repo** in the w8lbz org after each submit (free), as well as being covered by Proxmox snapshots.
- **FR-35** **Members-only.** The archive is behind the member login (§7.3).

### 4.7 Roster and chow
- **FR-35a** The roster Google Sheet is the **single source of truth** for people: members, guests and prospects, officer roles, and who can lead or edit. The app keeps only a read-only cache, and **no roster data is kept in git or in local config**.
- **FR-35b** Proposed extra columns in the sheet (to agree with whoever maintains the Discord side): `Short name`, `Aliases` (spellings seen in old minutes), `Officer role`, `Minutes access` (leader / editor / blank), `Attends remotely`, `Status` (active / SK / prospect / guest), `Email`.
- **FR-36** The roster's single source of truth is the Google Sheet (the Discord roster). It is read through the Google Sheets API with a service account and contains name, callsign, preferred short name ("Chris K", "Chris D", "Jim F"), **email** (for minutes delivery and login), status (active, SK, prospect), whether they attend remotely, and the Discord ID.
- **FR-37** Replace the website roster xlsx with an export generated from the Google Sheet.
- **FR-38** Keep the chow rotation in the app or the sheet, with swaps, blackout dates and next week's reminder. **[Q]** Should we move chow into the roster sheet as a second tab?

### 4.8 Personal items and names that are never recorded
- **FR-40a** A private **never-record list** of names, for example visiting family members or minors, lives only in the server's local config. It is never kept in git. Listed names are dropped from imported minutes, and the original PDF isn't served for those meetings. Nothing marks the removal, so it doesn't draw attention.
- **FR-40b** In the console, a guest can be entered as **visitor (name not recorded)**. They're counted in attendance but not named.


Members share personal news in their reports (health, jobs, family), and **those items belong in the minutes as members said them**. Members-only access is the privacy control.
- **FR-39** Summaries that go beyond the members-only archive, such as the Discord post, leave out personal items by default. The chair can include one.
- **FR-40** (Optional) A member can ask the chair to keep a specific item out of the minutes, and the chair can mark it "transcript only".

### 4.9 Statistics and guest tracking (built)
- **FR-43** Per meeting: the in-person, Teams, guest and total counts, plus the average.
- **FR-44** Per member: meetings attended (in person and on Teams), attendance rate, and when they last attended. Each member has a history page.
- **FR-45** Guests are grouped by callsign, or by name if there's no callsign, with their number of visits and first and last visit. The system marks guests who later became members (with the date they joined), and flags guests with 3 or more visits as **"regular, invite to join?"**. In the live console, the leader should see a guest's visit count when adding them (to do).
- **FR-46** (Later) Charts of attendance over time, and how many guests convert to members.

### 4.10 Reminders and Discord (later phase)
- **FR-41** Post a weekly reminder before the meeting: chow person, open action items, upcoming events.
- **FR-42** After submission, post the summary and link.

## 5. Non-functional requirements

- **NFR-1 Hosting.** The app, bot, storage and archive run in a VM or LXC on the clubhouse Proxmox node.
- **NFR-2 Cloud processing for now.** Audio goes to a cloud speech-to-text service and text goes to OpenRouter. Both sit behind **provider interfaces**, so they can move on-site later (faster-whisper/WhisperX, a local LLM) when the club has suitable hardware.
- **NFR-3 Cost.** A target of under $5/month. Spending caps are set with each provider.
- **NFR-4 Retention.** Audio is deleted N days after submit (**[Q]** 30?). Transcripts are kept for **[Q]**. Minutes are kept forever.
- **NFR-5 Operable by volunteers.** Deployed with `docker compose`. There is a runbook for "the bot didn't join" and "the browser stopped recording".
- **NFR-6 Login.** Members log in with an **email magic link** sent from the club Gmail to their address in the roster, and sessions last a long time. There are no shared passwords and no extra accounts.

## 6. Building blocks

| Need | Choice for Day 1 | Notes and future |
|---|---|---|
| Meeting bot | **Vexa** or **Attendee** (open source, headless Chromium), self-hosted on the Proxmox node | Phase-0 spike: must join *consumer* `teams.live.com` links as a guest, and must report active-speaker names. |
| Browser room capture | Web UI using `getUserMedia` and `MediaRecorder`, uploading chunks over WebSocket | Works in Chrome, Edge and Firefox on the chair's laptop. |
| Live speech-to-text | Cloud streaming service: **Deepgram** or **AssemblyAI** (both stream and support custom vocabulary) | **OpenRouter is mainly an LLM gateway, not a speech-to-text service with timestamps and diarization**, so a dedicated speech-to-text provider is needed. Expected cost: well under $1 per meeting (check current pricing). |
| Accurate pass and diarization | The same provider's batch API with diarization | Later: WhisperX and pyannote on-site, when there's a GPU. |
| Drafts, follow-ups, summaries, archive import | **OpenRouter** | Cents per meeting. A one-off import of 51 meetings costs about a dollar or two. |
| Web app | FastAPI with WebSockets; SQLite with FTS5 for search; Markdown files as the archive of record | |
| PDF | Markdown → HTML template → WeasyPrint | Reproduces the current look. |
| Email | Gmail API or an SMTP app password for w8lbzorg@gmail.com | Gmail's limit of about 500 recipients a day is plenty. |
| Roster | Google Sheets API (service account) | |

## 7. Decisions and open questions

### 7.1 Audio path (decided for Day 1)
Day 1 uses the chair's laptop: the browser records the room mic and the bot captures the remote side. A permanent Linux room PC and multiple mics come in later phases.

### 7.2 Compute (decided for now)
Speech-to-text runs on a cloud provider and the LLM work goes through OpenRouter. Everything sits behind interfaces, so on-site processing can replace it later.

### 7.3 Member access without Cloudflare
- **Phase 1 recommendation: Tailscale Funnel.**
  - It publishes just the web app at a public HTTPS address (`https://<host>.<tailnet>.ts.net`), using the tailnet the club already has. Members need no Tailscale accounts or clients.
  - The app's magic-link login (NFR-6) controls who gets in.
  - It also covers a remote chair.
- **Later (moving off Funnel):**
  - A custom domain such as `minutes.w8lbz.org`, once the club controls its DNS (see the backlog).
  - Or a small VPS running Caddy, with a WireGuard tunnel back to the clubhouse.
  - Or Headscale.
- Inside the clubhouse and on the tailnet, members can use the local address directly.
- **[Q]** What should happen to the PDFs already posted publicly on Zyro? Replace that page with a link to the archive?

### 7.4 M365 Copilot in Teams
Not recommended as the foundation.
- Its meeting recap needs paid licences, and it may not be available at all for free consumer Teams. **[Q]** Is that worth confirming?
- It hears the whole room as one participant (the leader's laptop).
- It knows nothing about the club's template, report queue, roster, chow list or archive.
- It ties the club to Teams, while Jitsi is on the table.
- At most, a Teams transcript, if one is ever available for free, could be imported as an extra source.

### 7.5 Open questions
- **[Q]** Do Vexa or Attendee handle consumer Teams? This is answered by the Phase-0 spike. If neither does, the fallback is to capture the **audio the laptop is playing** from the browser (Chrome on Windows can share system audio), which needs one extra click from the chair.
- **[Q]** Should the Financial Report be filled in or removed?
- **[Q]** Who owns the Discord bot token and the club Gmail account? There should be at least two people who can get in.
- **[Q]** Should guests be added to the roster automatically as prospects?
- **[Q]** How long should audio and transcripts be kept?

## 8. Phasing

| Phase | Scope |
|---|---|
| 0: Spikes (1–2 weeks) | Test Vexa and Attendee on the club's consumer Teams link. Test browser mic capture alongside Teams on Chris's laptop. Run one recorded meeting (with consent) through Deepgram or AssemblyAI to judge accuracy and diarization. Try converting a few historical PDFs to Markdown. |
| 1: MVP | Magic-link login and Tailscale Funnel. Start meeting with bot and room track. Live transcript. Chair console (attendance, report queue, sections). Live draft. Accurate pass. Review with the Sidebars panel. Submit: archive, PDF, email to the roster. |
| 2: Archive and smarts | Import the 51 historical meetings. Search, per-member and per-item history. Follow-up prompts. Tracked Old Business items, motions and actions. Flags and suggestions. Versioned corrections. |
| 3: Outreach | Discord summary and reminders, chow automation, Google Sheet as the roster of record, Zyro page replaced with a link. |
| 4: Hardware and on-site | Permanent Linux room PC, multiple mics, on-site speech-to-text and LLM if hardware allows, Jitsi bot, a permanent way to reach the app (VPS, Headscale, or a w8lbz.org subdomain). |

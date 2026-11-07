# W8LBZ Minutes

Meeting-minutes assistant for W8LBZ. See [REQUIREMENTS.md](REQUIREMENTS.md).

## Built so far
- **Archive:** each meeting is a Markdown file at `data/meetings/YYYY-MM-DD/minutes.md`, next to the original PDF.
- **Importer:** converts the historical PDFs (and `*CORRECTED*.txt`) into the archive with a plain parser, no AI. Imported meetings are marked "imported, unreviewed".
- **Web UI:**
  - archive list
  - minutes view in the modernized layout, with PDF download and a link to the original
  - full-text search
  - per-member history
  - attendance stats
  - guest tracking

## Run
```sh
curl -LsSf https://astral.sh/uv/install.sh | sh     # once
uv sync
uv run w8lbz-minutes roster                          # sync people from the roster Google Sheet
uv run w8lbz-minutes import archive                  # (re)build data/ from archive/
uv run w8lbz-minutes serve --host 0.0.0.0 --port 8765
uv run pytest -q
```
The roster sync needs a Google service-account key at `private/google-service-account.json`. Share the sheet with the account's email as Viewer.

PDF generation needs the system Pango library: `sudo apt install libpango-1.0-0 libpangoft2-1.0-0`.

## Deploy (Debian container)
As root on the container:
```sh
curl -fsSL https://raw.githubusercontent.com/W8LBZ/minutes/main/deploy/setup.sh | bash   # first time
/opt/w8lbz-minutes/deploy/update.sh                                                    # after each merge to main
```
Then put `club.yaml` and `google-service-account.json` in `/etc/w8lbz-minutes/`, and data in `/var/lib/w8lbz-minutes/`.
The app runs as the `minutes` user on port 8000. The roster syncs daily at 04:00.

## Login
Members sign in with a passkey, or with a one-time link emailed to their roster address.
- **Passkeys** only work at the HTTPS address in `club.yaml` (`auth.rp_id`).
- **Email** needs `W8LBZ_SMTP_USER` / `W8LBZ_SMTP_PASSWORD` (a Gmail app password) in `/etc/w8lbz-minutes/env`.
  Without them, links are written to the server log instead.
- **AI** (optional) needs `W8LBZ_OPENROUTER_KEY` in `/etc/w8lbz-minutes/env` and `ai: {model: ...}` in club.yaml. Each call is logged to `ai-log.jsonl` in the data folder (time, model, size, cost; never the text).
- **Recovery:** an admin on the server can print a one-time link for a member: `w8lbz-minutes login-link KO4CGQ`

Only officers and members ticked `minutes_editor` in the roster can use the leader console.

## Config
`club.yaml` (local only, git-ignored; copy from `club.example.yaml`) holds the club links, the leaders and editors lists, the private never-record list, and a stopgap roster. The Google Sheet roster will replace the roster part.

Club data (`archive/`, `data/`, `club.yaml`, credentials) is never committed.

**No login yet.** Keep the server on the LAN or tailnet only.

## Emailing the minutes
When a leader submits the minutes, the PDF goes to every roster member with an email address (except Inactive and Silent Key), each getting their own copy. Replies go to the meeting's leader.
- **Test mode:** while `club.yaml` has `email.only_to`, only those callsigns or addresses get mail; everyone else is withheld and logged. The submit dialog says which mode is on.
- Each meeting is emailed once. The outcome is in `emailed.json` beside the minutes, and leaders see it on the minutes page.
- **Removing a test meeting:** `w8lbz-minutes delete-meeting 2026-12-31`, then `systemctl restart w8lbz-minutes`.

## Member profiles
Members edit their own email, phone, address, birthday and sharing choices at `/profile`. The app writes those cells to the roster sheet, values only, and never changes columns, dropdowns or formatting.
- **Setup:** share the roster sheet with the service account as **Editor**, and add `birthday` and `share` columns to the Member Roster tab (headers exactly; any position).
- Each change is logged in `profile-changes.jsonl` in the data directory, emailed to members whose title includes Secretary, and can be undone by any officer at `/roster/changes`.
- Officers see all contact details; other members see only what each member shares.

## Admin mode
Callsigns listed under `admins:` in `club.yaml` get **Turn on admin mode** in the name menu. For an hour (or until turned off) that sign-in can see and do what officers can, with a red banner showing. Each switch is logged in `admin-log.jsonl` in the data directory.

In admin mode, a member's page has **View the app as …**: the app as that member sees it, read-only (no changes, and not their sign-in or passkey page), until **Stop** or admin mode ends. Also logged.

## Bylaws
`/bylaws` shows the club's constitution and bylaws from `bylaws.md` in the data directory (`/var/lib/w8lbz-minutes/bylaws.md` on the server). It's kept out of this public repo.

## Previewing a branch
`deploy/preview.sh BRANCH` runs a branch on the dev box (192.168.23.101, ports from 8100) so it can be tried before merging, with no change to CT103. It prints the address and a one-time sign-in link (passkeys don't work on a bare IP address).
- **Preview mode:** a banner on every page; email is recorded on the **outbox** page (`/preview/outbox`) instead of being sent; roster edits go to a local copy of the sheet.
- Each preview has its own checkout and a fresh copy of `data/` (meetings, roster cache, bylaws) on every update; its sign-ins are kept.
- `deploy/preview.sh --list` shows running previews; `deploy/preview.sh --stop BRANCH` stops one and deletes its copy.
- They run as user services (`systemctl --user`), so they stop if this user logs out entirely, unless lingering is enabled (`loginctl enable-linger`).

## Changes and releases
- Each PR adds a line under "Unreleased" in `CHANGELOG.md`, and removes its item from `ROADMAP.md` if it finishes one.
- To release: in a PR, rename "Unreleased" to the new version and date and bump `version` in `pyproject.toml` (then `uv lock`). When it merges, the Release workflow tags the merge commit `vX.Y.Z` and publishes a GitHub release with that CHANGELOG section. Deploy with `update.sh`; the footer then shows the new version.
- **Releases that need steps by hand** (a config change, a data file to copy, a new secret): add a line `- **Deploy notes:** …` to that version's CHANGELOG section, with any further steps indented under it. The admin Updates page shows them and asks the admin to confirm they're done before updating.
- **Updating from the app:** admins in admin mode see "Version X is available" and an **Updates** page with **Update now**. It writes `update-request.json` in the data folder; the root-owned `w8lbz-minutes-update.path` unit sees it and runs `deploy/update-from-app.sh` (which runs `update.sh` and records the result). `update.sh` installs and enables that unit, so the first update after this feature arrives is still by hand.
- Every pull request runs the tests (the Tests workflow).

## License
Copyright © 2026 Jim Flattery, KO4CGQ.

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. See [LICENSE](LICENSE).

If you run a modified version for others over a network, you must offer them its source code (AGPL section 13). The About page's source link does this for the club's copy.

## Chow schedule
`/chow` is the chow list; the app is the source of truth (state in `chow.json`, every change in `chow-log.jsonl`, both in the data directory).
- One-time import of the Secretary's spreadsheet: `w8lbz-minutes chow-import FILE.xlsx --order "Surname,Surname,..." --next Surname` prints what it found, including anything to check; add `--write` to save it (it won't overwrite an existing schedule).
- Members ask each other to swap; leaders edit directly; the console records provided, missed or covered on meeting night.

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

## Config
`club.yaml` (local only, git-ignored; copy from `club.example.yaml`) holds the club links, the leaders and editors lists, the private never-record list, and a stopgap roster. The Google Sheet roster will replace the roster part.

Club data (`archive/`, `data/`, `club.yaml`, credentials) is never committed.

**No login yet.** Keep the server on the LAN or tailnet only.

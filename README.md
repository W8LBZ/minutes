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
uv run w8lbz-minutes import archive                  # (re)build data/ from archive/
uv run w8lbz-minutes serve --host 0.0.0.0 --port 8765
uv run pytest -q
```
PDF generation needs the system Pango library: `sudo apt install libpango-1.0-0 libpangoft2-1.0-0`.

## Config
`club.yaml` (local only, git-ignored; copy from `club.example.yaml`) holds the club links, the leaders and editors lists, the private never-record list, and a stopgap roster. The Google Sheet roster will replace the roster part.

Club data (`archive/`, `data/`, `club.yaml`, credentials) is never committed.

**No login yet.** Keep the server on the LAN or tailnet only.

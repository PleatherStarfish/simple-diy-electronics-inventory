# Simple DIY Electronics Inventory

A free, offline desktop app for organizing your DIY electronics parts. Track what you have, where it lives, and whether you have enough to build your next project — all without an internet connection or cloud account.

Simple DIY Electronics Inventory runs on your Mac as a standalone app (or from source on Mac/Linux). Your data stays in a single local file on your machine, so there is nothing to sign up for, no subscription, and no server to maintain.

## Who is this for?

- **Synth builders and electronics hobbyists** who accumulate resistors, capacitors, ICs, and other components across multiple storage containers
- **Workshop organizers** who want to know at a glance what they have, where it is, and what they need to buy
- **BOM checkers** who want to import a bill of materials and instantly see which parts are in stock and which need ordering

## Quick start

### macOS app (easiest)

1. Download the latest `.dmg` from [GitHub Releases](https://github.com/danielmiller/simple-diy-electronics-inventory/releases).
2. Drag **Simple DIY Electronics Inventory** into your Applications folder.
3. Launch it from Applications.

> Signed releases should open normally. If macOS blocks an older build, right-click the app and choose **Open**, or go to **System Settings > Privacy & Security > Open Anyway**.

### From source (Mac or Linux)

Requires Python 3.11 or newer.

Using [uv](https://docs.astral.sh/uv/) (recommended):

```bash
git clone https://github.com/danielmiller/simple-diy-electronics-inventory.git
cd simple-diy-electronics-inventory
uv sync --dev
uv run python -m eurorack_inventory
```

Using pip:

```bash
git clone https://github.com/danielmiller/simple-diy-electronics-inventory.git
cd simple-diy-electronics-inventory
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m eurorack_inventory
```

## What you can do with it

### Manage your parts inventory

- Browse all your parts in a searchable, sortable table
- Edit part details inline: name, category, quantity, package, location, and supplier SKU
- Add richer metadata: manufacturer, MPN, supplier name, purchase URL, notes
- Adjust quantities quickly with `+1`, `-1`, `+10`, and `-10` buttons
- Add search aliases so you can find parts by alternate names
- Jump from a part directly to its storage location
- Find and merge duplicate parts with a side-by-side comparison dialog that highlights conflicts and lets you pick which fields to keep
- Bulk-normalize part names from the **Tools** menu to clean up inconsistent naming

### Organize physical storage

- Create storage containers: grid boxes with rows and columns, binders with numbered card slots, or custom bins
- See your storage laid out visually — each container shows which parts are in which slots
- Drag and drop parts between compartments
- Merge multiple empty grid cells into larger regions for bigger components, and split them back apart later
- Resize containers with validation so you never accidentally lose occupied slots
- See utilization counts per container at a glance

### Auto-assign parts to storage

Instead of manually sorting every component into a slot, let the app do it:

- **Preview before applying** — see exactly what would go where before committing
- Choose a mode: **incremental** (only place currently unassigned parts) or **full rebuild** (clear and recompute)
- Choose a scope: all parts, a hand-picked selection, or a single category
- Optionally target a specific container (e.g. "fill this binder box") with an optional quantity filter to prioritize parts above a threshold
- Parts are classified by size and matched to compatible slots, with a flexible compatibility system that prefers ideal fits but allows alternatives
- If a part's storage class changes, the app automatically unassigns it from any incompatible slot
- Every assignment run is saved so you can **undo** it later

### Import and check bills of materials (BOMs)

- Import BOMs from Excel spreadsheets or PDF documents (PDF requires optional Java + tabula-py)
- Normalize and edit BOM line items: component type, value, quantity, package
- Match BOM items to your existing inventory with fuzzy search — see match scores and reasons
- Create new inventory parts directly from unmatched BOM items, pre-filled with BOM data
- Filter by match status: all, matched, or unmatched
- Bulk-delete BOM sources you no longer need
- Normalize BOM names automatically from the **Tools** menu (cleans up prefixes, suffixes, and formatting)
- Promote a fully verified BOM to a project for build tracking
- Generate a **shopping list** from one or more BOMs showing what you need, what you have, and what to buy — then copy it to clipboard or export as CSV

### Track projects and builds

- Browse your projects in a dedicated tab with maker, revision, and notes
- See part availability at a glance: the app compares your BOM requirements with current stock
- Create build instances with optional nicknames and track their status
- Rename projects via right-click context menu

### Search across everything

- Type a few characters and the app searches across part names, aliases, categories, supplier SKUs, and package types
- Fuzzy matching means you don't need exact spelling — close matches surface automatically
- Results are ranked by relevance with bonuses for exact and substring matches

### Back up and restore your data

Your inventory lives in a single SQLite database file. The app provides two ways to protect it:

**Database backup** (exact snapshot — best for disaster recovery):
- From the app: **File > Export Backup...** / **File > Restore Backup...**
- From the command line: `python -m eurorack_inventory --export-backup ~/Desktop/backup.db`

**CSV export** (human-readable — great for sharing or spreadsheet editing):
- From the app: **File > Export as CSV...** / **File > Import from CSV...**
- From the command line: `python -m eurorack_inventory --export-csv ~/Desktop/data.zip`

Restore always creates a safety copy of your current database first. CSV import replaces all data atomically and rolls back if any integrity check fails.

### Import from an existing spreadsheet

If you already track parts in Excel, you can import them directly:

```bash
python -m eurorack_inventory --import ./parts_inventory.xlsx
```

The importer reads columns for Category, Component, Total Qty, Tayda SKU, and Merged From. It automatically creates search aliases and places imported parts in the default Unassigned location.

## Default data locations

Your database is created automatically the first time you launch the app:

| Platform | Path |
| --- | --- |
| macOS | `~/Library/Application Support/Simple DIY Electronics Inventory/eurorack_inventory.db` |
| Linux | `~/.local/share/simple-diy-electronics-inventory/eurorack_inventory.db` |

Use `--db PATH` to open a different database file. Runtime logs are stored in a `logs/` folder next to the database.

## Command-line reference

```bash
python -m eurorack_inventory --help
```

| Flag | Description |
| --- | --- |
| `--db PATH` | Path to the SQLite database file |
| `--import PATH` | Import an Excel workbook before launching the GUI |
| `--import-mode {replace_snapshot,merge_quantities}` | Import strategy (both currently produce the same result) |
| `--headless-import` | Run the import and exit without opening the GUI |
| `--bootstrap-demo-storage` | Create demo containers and the default Unassigned location |
| `--export-backup PATH` | Export a full database backup and exit |
| `--restore-backup PATH` | Restore the database from a backup file and exit |
| `--export-csv PATH` | Export all data as CSV files in a zip archive and exit |
| `--import-csv PATH` | Import data from a CSV zip archive (replaces all current data) and exit |

## Limitations

- The spreadsheet importer does not use source location columns to auto-place parts.
- BOM PDF import requires Java and the optional `tabula-py` dependency (`pip install -e ".[bom-pdf]"`).
- The app supports importing and matching BOMs but does not yet support authoring a BOM from scratch.

---

## Technical details

The rest of this README covers architecture, build processes, and development setup for contributors.

### Architecture overview

The app is built in Python with a PySide6 (Qt) GUI and a single SQLite database. There is no server or network component.

```text
src/eurorack_inventory/
  __main__.py          # module entry point
  main.py              # CLI parsing and app startup
  app.py               # AppContext construction and wiring
  config.py            # database/log/resource paths
  db/                  # SQLite wrapper and SQL migrations
  domain/              # dataclasses, enums, storage geometry helpers
  repositories/        # SQL-backed data access
  services/            # business logic
  ui/                  # PySide6 screens, dialogs, and models
  resources/           # icons and app resources
tests/                 # pytest suite
scripts/               # build helpers
```

The codebase is split into explicit layers:

- **db/** — SQLite connection management and migration runner
- **domain/** — dataclasses, enums, and pure storage/grid geometry helpers
- **repositories/** — direct SQL access for parts, storage, projects, and audit events
- **services/** — business logic (inventory, import, search, storage, auto-assignment, BOM extraction, classifier, settings)
- **ui/** — PySide6 screens, dialogs, Qt models, and styling

This separation keeps business rules outside the UI and makes the service layer testable without launching the desktop app.

### Database schema

The app uses a single SQLite file with WAL journal mode and foreign keys enabled. Schema changes are tracked by numbered SQL migrations applied via `PRAGMA user_version`.

For the full schema walkthrough and ER diagram, see [docs/DATABASE_DESIGN.md](docs/DATABASE_DESIGN.md).

| Table | Purpose |
| --- | --- |
| `parts` | Canonical component record with metadata, total qty, denormalized primary slot shortcut, and storage class override |
| `part_aliases` | Extra searchable names tied to a part |
| `part_locations` | Authoritative multi-location placement rows with per-slot qty |
| `storage_containers` | Named physical container with type and JSON metadata |
| `storage_slots` | Individual compartment or merged region inside a container |
| `modules` | Build target (called "projects" in the UI) |
| `bom_lines` | Required quantity of a part for a project |
| `builds` | Concrete build instance of a project |
| `build_updates` | Status or note entries for a build |
| `settings` | Stored JSON/text configuration such as classifier thresholds |
| `audit_events` | Append-only record of user-visible changes |
| `assignment_runs` | Stored plan and pre-run snapshot for undo |

### Search implementation

The search index is built in memory from repository data. Each part contributes candidates for its name, category, supplier SKU, package, and aliases. Scoring uses `rapidfuzz.fuzz.WRatio` with bonuses for exact matches, substring matches, and full-token coverage. Source weights ensure names and aliases rank higher than category or package matches.

### Auto-assignment implementation

Auto-assignment is a two-step plan-then-apply system:

1. **Plan** — classifies parts into storage classes (`small_short_cell`, `large_cell`, `long_cell`, `binder_card`), gathers available slots, and packs parts using a category-affinity first-fit strategy with a flexible compatibility matrix
2. **Apply** — writes slot assignments and stores the run for undo

Classification uses regex matching against part names/categories plus quantity thresholds. Users can override the storage class per part. The compatibility matrix allows cross-class placement with penalties, preferring ideal fits but reducing unassigned counts.

### Dependencies

| Dependency | Purpose |
| --- | --- |
| Python 3.11+ | Runtime |
| PySide6 | Desktop GUI |
| RapidFuzz | Fuzzy text search |
| pandas | Spreadsheet import |
| openpyxl | Excel file reading |
| tabula-py | PDF BOM import (optional, requires Java) |
| pytest | Testing (dev) |
| PyInstaller | macOS app bundling (dev) |

### Building the macOS app

```bash
pip install -e ".[dev]"
bash scripts/build_macos.sh
```

Or using Make:

```bash
make dmg
```

The build script removes `build/` and `dist/`, runs PyInstaller, applies code signing (ad-hoc for local builds, Developer ID when configured), and optionally creates a DMG if `create-dmg` is installed (`brew install create-dmg`).

### Notarized GitHub releases

To publish releases that open without Gatekeeper warnings, configure these GitHub Actions secrets:

| Secret | Purpose |
| --- | --- |
| `MACOS_CERTIFICATE_P12_BASE64` | Base64-encoded Developer ID Application certificate |
| `MACOS_CERTIFICATE_PASSWORD` | Password for the .p12 file |
| `APPLE_SIGNING_IDENTITY` | Full signing identity string |
| `APPLE_ID` | Apple ID email for notarization |
| `APPLE_TEAM_ID` | Apple Developer team ID |
| `APPLE_APP_PASSWORD` | App-specific password for notarization |

### Make targets

| Target | Description |
| --- | --- |
| `make install` | Install with BOM-PDF support |
| `make install-dev` | Install with dev and BOM-PDF extras |
| `make run` | Launch the app |
| `make test` | Run the test suite |
| `make clean` | Remove build and dist directories |
| `make dmg` | Build the macOS app bundle |
| `make release VERSION=x.y.z` | Bump version, commit, tag, and push |

### Running tests

```bash
pytest
```

The test suite covers search, inventory CRUD, spreadsheet import, storage geometry, auto-assignment planning and undo, classifier rules, BOM operations, and selected UI behavior.

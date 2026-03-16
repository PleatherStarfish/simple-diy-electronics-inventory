# Simple DIY Electronics Inventory

Simple DIY Electronics Inventory is a local-first desktop app for tracking DIY electronics parts, their physical storage locations, and the inventory needed for module builds. It is implemented in Python with a PySide6 GUI and a single SQLite database file, so there is no server, no cloud account, and no separate backend to deploy.

This repository contains both the desktop application and the core logic for importing spreadsheets, fuzzy searching parts, modeling physical storage, planning storage assignments, and checking project/BOM availability.

## What the app is for

The project is designed around a practical workshop workflow:

- keep one canonical record for each part
- know how many of that part you currently have
- know where that part physically lives
- quickly find parts by name, alias, package, or supplier SKU
- estimate whether a project can be built from current stock
- reduce manual sorting by auto-assigning unplaced parts into available storage

## Current implementation scope

The codebase is already useful, but it is important to describe its current implementation precisely:

- Each part currently stores a single integer `qty` and one optional `slot_id`. Earlier stock-lot ideas still appear in older comments and migration history, but the active schema stores quantity and location directly on the `parts` table.
- The UI currently creates and edits grid boxes and binders, plus an automatic fallback container named `Unassigned` with a `Main` slot. The domain model and database also allow generic bins and drawers.
- The Projects tab supports browsing, availability display, build creation, and renaming. Projects can also be created by promoting a fully verified BOM from the BOMs tab.
- The CLI accepts `--import-mode replace_snapshot` and `--import-mode merge_quantities`. In the current importer implementation, both values are validated and recorded in audit data, but row handling is the same for both modes.

## User-facing features

### Inventory

- List all parts in a searchable table
- Edit key fields inline: name, category, quantity, package, location, and supplier SKU
- Create and edit parts with richer metadata: manufacturer, MPN, supplier name, purchase URL, notes, and storage-class override
- Adjust quantity with quick `+1`, `-1`, `+10`, and `-10` controls
- Add search aliases for alternate part names
- Jump from a selected part directly to its storage location
- Prevent deleting a part that is still referenced by a project BOM

### Storage

- Create storage containers for:
  - grid boxes with row/column metadata
  - binders with numbered cards
  - the default `Unassigned / Main` fallback slot
- Display storage visually in the Storage tab
- Merge multiple empty grid cells into one contiguous rectangular region
- Unmerge previously merged regions back into individual cells
- Resize grid boxes and binders with validation to avoid losing occupied slots
- Drag a part from one storage compartment to another
- If a part is dropped onto an occupied slot, the displaced part is automatically moved to `Unassigned / Main`
- Delete empty containers with an explicit typed confirmation challenge
- Show per-container utilization counts

### Auto-assignment

- Preview assignments before applying them
- Run in either:
  - `incremental` mode, which only assigns currently unassigned parts
  - `full_rebuild` mode, which clears and recomputes assignments for the selected scope
- Scope runs to:
  - all parts
  - currently selected parts
  - a single category
- Store every assignment run in the database so the latest run can be undone
- Report estimated additional storage needed when there are not enough matching slots

### BOMs

- Import and normalize bills of materials in a dedicated BOMs tab
- Edit normalized items inline: component type, value, quantity, and package hint
- Filter the normalized table by match status: all, matched, or unmatched
- Match BOM items to existing inventory parts with fuzzy search scoring and match-reason display
- Create new inventory parts directly from unmatched BOM items, pre-populated with BOM metadata
- Skip items that do not need matching
- Re-normalize a BOM after editing raw items
- Issues banner highlights problems such as high dropout rates, unmatched items, or missing source files
- Promote a fully verified BOM to a project for build tracking (all items must be verified first)
- Generate a shopping list from one or more selected BOMs showing quantities needed, available, and to buy
- Copy the shopping list to clipboard or export it as CSV

### Projects and builds

- Display stored projects in a dedicated Projects tab
- Show project maker, revision, and notes
- Rename projects via context menu
- Calculate part availability by comparing BOM requirements with current inventory quantities
- Create build instances for a project with an optional nickname
- Persist build records in the database

### Search

- Use RapidFuzz-based fuzzy search over:
  - canonical part names
  - aliases
  - categories
  - supplier SKUs
  - default package names
- Favor exact and substring matches with source-specific weighting
- Hydrate final search results from SQLite after ranking in memory

### Import and audit visibility

- Import an existing Excel inventory workbook
- Automatically create searchable aliases during import
- Persist audit events for part edits, moves, imports, assignments, and storage changes
- Show recent audit events in a dockable panel
- Capture runtime logs in memory and in rotating log files, with a dockable runtime log viewer

## How the current implementation works

### Application startup

`python -m eurorack_inventory` enters through `src/eurorack_inventory/main.py`, which:

1. parses CLI arguments
2. resolves the database path
3. builds an application context
4. applies SQLite migrations
5. configures logging
6. constructs repositories and services
7. ensures the default `Unassigned / Main` location exists
8. rebuilds the in-memory search index
9. launches the PySide6 main window unless `--headless-import` was requested

### Persistence model

The app uses a single SQLite database file. The connection wrapper enables:

- foreign keys
- WAL journal mode
- `synchronous = NORMAL`

Schema changes are tracked by numbered SQL migrations in `src/eurorack_inventory/db/migrations/`, applied via `PRAGMA user_version`.

### Core database objects

| Concept | Stored as | Purpose |
| --- | --- | --- |
| Part | `parts` | Canonical component record with metadata, `qty`, optional `slot_id`, and optional `storage_class_override` |
| Alias | `part_aliases` | Extra searchable names tied to a part |
| Storage container | `storage_containers` | Named physical container with type and JSON metadata |
| Storage slot | `storage_slots` | Individual compartment or merged region inside a container |
| Project | `modules` | Build target; the service/UI calls these "projects" |
| BOM line | `bom_lines` | Required quantity of a part for a project |
| Build | `builds` | A concrete build instance of a project |
| Build update | `build_updates` | Status or note entries for a build |
| Setting | `settings` | Stored JSON/text configuration such as classifier thresholds |
| Audit event | `audit_events` | Append-only record of user-visible changes |
| Assignment run | `assignment_runs` | Stored plan and pre-run snapshot for undo |

There is also a SQL view named `part_inventory_summary` used for fast inventory-table hydration.

### Repository and service layers

The project is intentionally split into explicit layers:

- `db/`
  - SQLite connection management and migration runner
- `domain/`
  - dataclasses, enums, and pure storage/grid geometry helpers
- `repositories/`
  - direct SQL access for parts, storage, projects, and audit events
- `services/`
  - business logic such as inventory editing, import, search, storage configuration, auto-assignment, dashboard counts, and settings
- `ui/`
  - PySide6 screens, dialogs, Qt models, and app styling

This keeps most business rules outside the UI, which makes the service layer testable without launching the desktop app.

### Search implementation

The search index is built in memory from repository data:

- one candidate for normalized part name
- optional candidates for category, supplier SKU, and package
- one candidate per alias

Search uses `rapidfuzz.fuzz.WRatio` with:

- a large bonus for exact normalized matches
- a smaller bonus for substring matches
- an additional bonus when all query tokens appear in the candidate text
- source weights so names and aliases matter more than category or package matches

Only results above the minimum score threshold are returned. The final part IDs are then reloaded through the repository and shown via `part_inventory_summary`.

### Storage implementation

Storage is modeled generically, but the current UI focuses on two container types:

- `grid_box`
- `binder`

Grid slots can have coordinates and can represent either single cells or merged rectangular regions. The storage service validates that:

- a grid region stays within container bounds
- merged cells form a contiguous rectangle
- merged or removed cells do not contain stock
- shrinking a grid does not cut through an existing merged cell

Slot metadata is used to distinguish:

- small vs large cells
- short vs long cells
- binder card bag counts

### Auto-assignment implementation

Auto-assignment is a two-step system:

1. `plan()`
   - gathers parts for the requested scope
   - classifies each part into a storage class
   - gathers currently available slots by storage class
   - packs parts into slots using a category-affinity first-fit strategy
   - estimates additional storage requirements for leftover parts
2. `apply_plan()`
   - optionally clears existing slot assignments for `full_rebuild`
   - writes new slot assignments
   - stores the run, plan, and original snapshot in `assignment_runs`

Undo restores the saved snapshot, but intentionally leaves alone any part that has been manually moved since the assignment run.

The classifier currently assigns parts into four storage classes:

- `small_short_cell`
- `large_cell`
- `long_cell`
- `binder_card`

Classification is based on regex matching against part names/categories plus quantity thresholds, and users can override the storage class per part.

### Spreadsheet import implementation

The importer expects an Excel sheet named `Consolidated Inventory`.

The current implementation reads these columns:

- `Category`
- `Component`
- `Total Qty`
- `Tayda SKU`
- `Merged From`

Import behavior today:

- rows with a blank component name are skipped
- rows with missing, invalid, or non-positive quantities are skipped and reported as warnings
- imported parts are upserted into the database
- imported parts are placed in `Unassigned / Main`
- an alias of `<component> <category>` is added when a category is present
- an alias matching the Tayda SKU is added when present
- other spreadsheet columns are currently ignored by the importer

## Installation

### macOS standalone app

1. Download the latest `.dmg` from [GitHub Releases](https://github.com/danielmiller/simple-diy-electronics-inventory/releases).
2. Drag **Simple DIY Electronics Inventory** into `Applications`.
3. Launch it from `Applications`.
4. Signed releases should open normally. If you are testing an older ad-hoc build, macOS may require `right-click -> Open` or `Privacy & Security -> Open Anyway`.

### From source

Requires Python 3.11 or newer.

Recommended with `uv`:

```bash
git clone https://github.com/danielmiller/simple-diy-electronics-inventory.git
cd simple-diy-electronics-inventory
uv sync --dev
uv run python -m eurorack_inventory
```

Traditional virtualenv setup:

```bash
git clone https://github.com/danielmiller/simple-diy-electronics-inventory.git
cd simple-diy-electronics-inventory
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m eurorack_inventory
```

Base runtime dependencies:

- Python 3.11+
- PySide6
- RapidFuzz
- pandas
- openpyxl

Development extras:

- pytest
- PyInstaller

## Running the app

Basic launch:

```bash
python -m eurorack_inventory
```

Open a custom database file:

```bash
python -m eurorack_inventory --db ./my_inventory.db
```

Import a workbook and then launch the UI:

```bash
python -m eurorack_inventory --import ./parts_inventory.xlsx
```

Run a headless import and exit:

```bash
python -m eurorack_inventory --import ./parts_inventory.xlsx --headless-import
```

Create the example containers defined by the current demo bootstrap:

```bash
python -m eurorack_inventory --bootstrap-demo-storage
```

## CLI reference

```bash
python -m eurorack_inventory --help
```

| Flag | Description |
| --- | --- |
| `--db PATH` | Path to the SQLite database file |
| `--import PATH` | Import an Excel workbook before optionally launching the GUI |
| `--import-mode {replace_snapshot,merge_quantities}` | Accepted import mode values; current importer behavior is the same for both |
| `--headless-import` | Run the import and exit without opening the GUI |
| `--bootstrap-demo-storage` | Create the demo containers plus the default unassigned location |
| `--export-backup PATH` | Export a full SQLite database backup to PATH and exit |
| `--restore-backup PATH` | Restore the database from a SQLite backup file and exit |
| `--export-csv PATH` | Export all data as CSV files in a zip archive and exit |
| `--import-csv PATH` | Import data from a CSV zip archive (replaces all current data) and exit |

## Backup and restore

The app provides two complementary ways to protect and export your data.

### SQLite backup (exact database snapshot)

This creates a byte-level copy of the database, preserving all tables, foreign keys, IDs, and migration state. Recommended for disaster recovery.

From the UI: **File > Export Backup...** and **File > Restore Backup...**

From the CLI:

```bash
python -m eurorack_inventory --export-backup ~/Desktop/backup.db
python -m eurorack_inventory --restore-backup ~/Desktop/backup.db
```

Restore always creates a safety copy of the current database before replacing it. The app closes after a UI restore so you can relaunch into the restored data.

### CSV export and import (human-readable)

This exports all tables as CSV files inside a zip archive. The archive can be opened, diffed, or edited in any spreadsheet tool.

From the UI: **File > Export as CSV...** and **File > Import from CSV...**

From the CLI:

```bash
python -m eurorack_inventory --export-csv ~/Desktop/data.zip
python -m eurorack_inventory --import-csv ~/Desktop/data.zip
```

CSV import replaces all current data atomically. If any foreign-key violation is detected the import is rolled back and the database is left untouched.

## Default filesystem locations

If `--db` is not provided, the app creates its data under a platform-specific app-data directory.

- macOS database:
  - `~/Library/Application Support/Simple DIY Electronics Inventory/eurorack_inventory.db`
- Linux database:
  - `~/.local/share/simple-diy-electronics-inventory/eurorack_inventory.db`
- Runtime logs:
  - `<database directory>/logs/`

## Building the macOS app

The repository includes a PyInstaller spec and a helper build script.

```bash
pip install -e ".[dev]"
bash scripts/build_macos.sh
```

The script currently:

- removes `build/` and `dist/`
- runs PyInstaller with `EurorackInventory.spec`
- applies ad-hoc code signing by default for local builds
- signs with a Developer ID identity when `APPLE_SIGNING_IDENTITY` is set
- notarizes and staples the DMG when `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_TEAM_ID`, and `APPLE_APP_PASSWORD` are set
- optionally creates `dist/Simple DIY Electronics Inventory.dmg` if `create-dmg` is installed

If needed:

```bash
brew install create-dmg
```

### Notarized GitHub releases

To publish a macOS release that opens without Gatekeeper warnings, configure these GitHub Actions secrets:

- `MACOS_CERTIFICATE_P12_BASE64`: Base64-encoded Developer ID Application certificate export
- `MACOS_CERTIFICATE_PASSWORD`: Password for that `.p12`
- `APPLE_SIGNING_IDENTITY`: Full signing identity, for example `Developer ID Application: Your Name (TEAMID)`
- `APPLE_ID`: Apple ID email used for notarization
- `APPLE_TEAM_ID`: Apple Developer team ID
- `APPLE_APP_PASSWORD`: App-specific password for notarization

Without those secrets, local builds will still work for development, but downloaded apps will be blocked by macOS Gatekeeper.

## Running tests

```bash
pytest
```

The current test suite covers:

- search behavior
- inventory CRUD and reassignment
- spreadsheet import
- storage geometry and configuration
- auto-assignment planning and undo behavior
- classifier rules and settings persistence
- BOM repository, service, extraction, and normalization
- selected UI dialog and screen behavior

## Repository layout

```text
src/eurorack_inventory/
  __main__.py          # module entry point
  main.py              # CLI parsing and app startup
  app.py               # AppContext construction and wiring
  config.py            # database/log/resource paths
  db/                  # SQLite wrapper and SQL migrations
  domain/              # dataclasses, enums, storage geometry helpers
  repositories/        # SQL-backed repositories
  services/            # business logic
  ui/                  # PySide6 screens, dialogs, and models
  resources/           # icons and app resources
tests/                 # pytest suite
scripts/               # build helpers
```

## Practical limitations to know about

- One part currently maps to one stored quantity and one primary location. If you need the same part split across multiple physical locations, that is not yet modeled in the active schema.
- The importer does not currently use spreadsheet location columns to place parts automatically.
- The demo bootstrap creates named example containers, but it is not a full sample dataset with seeded part assignments.
- The main desktop UI supports BOM import, matching, and promotion to projects, but does not yet support manually authoring a BOM from scratch.

## Summary

This project is a desktop-first inventory system with explicit storage modeling, a pragmatic service-layer architecture, and enough implementation depth to support real workshop use today. Its strongest current areas are local persistence, storage visualization, fuzzy part search, spreadsheet import, and storage auto-assignment. The code is structured so that richer project workflows, storage behaviors, and import logic can continue to grow without requiring a backend rewrite.

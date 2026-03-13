# Simple DIY Synth Inventory

A local-first desktop app for tracking Eurorack DIY parts, storage locations, and module builds. Built with PySide6 and SQLite.

## Download & Install

### macOS (standalone app)

1. Download the latest `.dmg` from [Releases](../../releases)
2. Open the `.dmg` and drag **Simple DIY Synth Inventory** to your Applications folder
3. Launch from Applications (right-click > Open on first launch if macOS blocks it)

The app stores its database at `~/Library/Application Support/Simple DIY Synth Inventory/`.

### From source (macOS / Linux)

Requires **Python 3.11+**.

```bash
git clone https://github.com/danielmiller/simple-diy-synth-inventory.git
cd simple-diy-synth-inventory
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Launch the app:

```bash
python -m eurorack_inventory
```

The database is created automatically at:
- **macOS**: `~/Library/Application Support/Simple DIY Synth Inventory/eurorack_inventory.db`
- **Linux**: `~/.local/share/simple-diy-synth-inventory/eurorack_inventory.db`

You can also specify a custom database path:

```bash
python -m eurorack_inventory --db ./my_inventory.db
```

## Importing a spreadsheet

If you have an existing parts inventory in Excel, import it:

```bash
python -m eurorack_inventory --import ./parts_inventory.xlsx --headless-import
```

Or use **File > Import Parts...** from within the app.

The importer reads a sheet named `Consolidated Inventory` with columns: `Category`, `Component`, `Total Qty`, `Tayda SKU`, `Merged From`.

## Features

- **Part management** — create, edit, delete parts with category, manufacturer, MPN, package type, supplier info
- **Quantity tracking** — adjust stock with +1/-1/+10/-10 buttons directly on each part
- **Fuzzy search** — find parts by name, alias, SKU, or package type using RapidFuzz
- **Storage model** — grid boxes, binders with numbered cards, bins and drawers
- **Module & BOM tracking** — track module builds and their bills of materials
- **Spreadsheet import** — bulk-import from Excel workbooks
- **Audit log** — every change is logged (toggle via View menu)
- **Local-first** — single SQLite file, no server, no account needed

## CLI reference

```
python -m eurorack_inventory --help
```

| Flag | Description |
|---|---|
| `--db PATH` | Path to SQLite database (default: platform-specific app support dir) |
| `--import PATH` | Import a spreadsheet before launching |
| `--import-mode {replace_snapshot,merge_quantities}` | How to handle existing data on import |
| `--headless-import` | Import and exit without opening the UI |
| `--bootstrap-demo-storage` | Create example storage containers |

## Building from source (macOS .app)

```bash
pip install -e ".[dev]"
bash scripts/build_macos.sh
```

This produces `dist/Simple DIY Synth Inventory.app` (and a `.dmg` if `create-dmg` is installed: `brew install create-dmg`).

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

## Project layout

```
src/eurorack_inventory/
  db/            # SQLite connection, migrations
  domain/        # Dataclasses, enums, storage geometry
  repositories/  # Data access layer
  services/      # Business logic (inventory, search, import, storage, modules)
  ui/            # PySide6 screens and dialogs
  resources/     # App icon assets
tests/
scripts/         # Build scripts
```

## Dependencies

- Python 3.11+
- PySide6
- RapidFuzz
- pandas + openpyxl (for spreadsheet import)
- PyInstaller (dev, for building .app)

# Architecture

## Goals

- keep the app local, fast, and easy to reason about
- make physical storage first-class, not an afterthought
- preserve future room for BOM and build workflows
- avoid heavy framework overhead

## Layered design

### 1. Database
SQLite stores all persistent state in one file.

- migrations are versioned SQL files
- foreign keys are enabled on every connection
- WAL mode is enabled for responsive small writes
- repositories are thin and explicit

### 2. Domain
The domain layer contains dataclasses and pure logic such as:

- grid label conversion
- grid region parsing
- rectangle overlap validation
- import normalization
- search normalization

### 3. Services
Services implement business rules:

- move part of a stock lot to another slot
- merge compatible lots
- validate grid-slot overlap
- import spreadsheet snapshots
- keep audit trails
- rebuild the fuzzy search index

### 4. UI
The UI is intentionally plain:

- one main window
- search at the top
- master-detail workflows
- one dock for runtime logs

## Key design choices

### Stock lots hold quantity
A part can exist in many places at once. Quantities therefore live on stock lots.

### Containers and slots are generic
The app models:

- grid boxes
- binders
- drawers
- generic bins

This prevents a fixed grid assumption from leaking through the whole system.

### Search is in-memory, data is in SQLite
Search uses a lightweight in-memory cache built from canonical part names, aliases, categories, and supplier SKUs. Once candidate ids are found, SQLite is used to hydrate details and totals.

## Logging and visibility

There are two visibility layers:

1. runtime logs
   - rotating file handler
   - in-memory log handler exposed in the UI

2. audit events
   - persisted in the database
   - records key changes like imports and stock edits

## Typical data flow

### Search
1. user types a query
2. `SearchService` normalizes and scores candidates
3. matching part ids are hydrated from the repository
4. the inventory table updates

### Adjust stock
1. user selects a stock lot
2. UI calls `InventoryService.adjust_stock`
3. repository updates or deletes the lot
4. service writes an audit event
5. UI refreshes selected views

### Import spreadsheet
1. importer loads the workbook
2. blank rows are skipped
3. parts are upserted
4. lots are placed in an import slot
5. an audit event is written with summary counts

## Future extension points

- low-stock alerts
- import preview and mapping UI
- multi-vendor purchase history
- structured per-build pulled-part allocations
- undo/redo commands

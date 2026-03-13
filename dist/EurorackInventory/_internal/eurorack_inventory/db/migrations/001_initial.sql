PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    category TEXT,
    manufacturer TEXT,
    mpn TEXT,
    supplier_name TEXT,
    supplier_sku TEXT,
    purchase_url TEXT,
    default_package TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_parts_normalized_name ON parts(normalized_name);
CREATE INDEX IF NOT EXISTS idx_parts_category ON parts(category);

CREATE TABLE IF NOT EXISTS part_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id INTEGER NOT NULL,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    UNIQUE(part_id, normalized_alias),
    FOREIGN KEY(part_id) REFERENCES parts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_part_aliases_normalized_alias
    ON part_aliases(normalized_alias);

CREATE TABLE IF NOT EXISTS storage_containers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    container_type TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    notes TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS storage_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    container_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    slot_type TEXT NOT NULL,
    ordinal INTEGER,
    x1 INTEGER,
    y1 INTEGER,
    x2 INTEGER,
    y2 INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    notes TEXT,
    UNIQUE(container_id, label),
    FOREIGN KEY(container_id) REFERENCES storage_containers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_storage_slots_container_id
    ON storage_slots(container_id);

CREATE TABLE IF NOT EXISTS stock_lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id INTEGER NOT NULL,
    slot_id INTEGER NOT NULL,
    qty INTEGER NOT NULL CHECK(qty >= 0),
    unit TEXT NOT NULL DEFAULT 'pcs',
    packaging TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    notes TEXT,
    source_tag TEXT,
    source_row INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(part_id) REFERENCES parts(id) ON DELETE CASCADE,
    FOREIGN KEY(slot_id) REFERENCES storage_slots(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_stock_lots_part_id ON stock_lots(part_id);
CREATE INDEX IF NOT EXISTS idx_stock_lots_slot_id ON stock_lots(slot_id);
CREATE INDEX IF NOT EXISTS idx_stock_lots_source_tag ON stock_lots(source_tag);

CREATE TABLE IF NOT EXISTS modules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    maker TEXT NOT NULL,
    revision TEXT,
    source_url TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS bom_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id INTEGER NOT NULL,
    part_id INTEGER NOT NULL,
    qty_required INTEGER NOT NULL CHECK(qty_required > 0),
    reference_note TEXT,
    is_optional INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(module_id) REFERENCES modules(id) ON DELETE CASCADE,
    FOREIGN KEY(part_id) REFERENCES parts(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_bom_lines_module_id ON bom_lines(module_id);

CREATE TABLE IF NOT EXISTS builds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id INTEGER NOT NULL,
    nickname TEXT,
    status TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    notes TEXT,
    FOREIGN KEY(module_id) REFERENCES modules(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS build_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    build_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT,
    note TEXT NOT NULL,
    FOREIGN KEY(build_id) REFERENCES builds(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_build_updates_build_id ON build_updates(build_id);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    message TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events(created_at);

CREATE VIEW IF NOT EXISTS part_inventory_summary AS
SELECT
    p.id AS part_id,
    p.name AS name,
    p.category AS category,
    p.supplier_sku AS supplier_sku,
    COALESCE(SUM(sl.qty), 0) AS total_qty,
    COALESCE(GROUP_CONCAT(sc.name || ' / ' || ss.label, '; '), '') AS locations,
    p.notes AS notes
FROM parts p
LEFT JOIN stock_lots sl ON sl.part_id = p.id
LEFT JOIN storage_slots ss ON ss.id = sl.slot_id
LEFT JOIN storage_containers sc ON sc.id = ss.container_id
GROUP BY p.id;

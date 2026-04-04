CREATE TABLE IF NOT EXISTS part_locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id INTEGER NOT NULL,
    slot_id INTEGER NOT NULL,
    qty INTEGER NOT NULL CHECK(qty >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(part_id, slot_id),
    FOREIGN KEY(part_id) REFERENCES parts(id) ON DELETE CASCADE,
    FOREIGN KEY(slot_id) REFERENCES storage_slots(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_part_locations_part_id
    ON part_locations(part_id);

CREATE INDEX IF NOT EXISTS idx_part_locations_slot_id
    ON part_locations(slot_id);

INSERT INTO storage_containers (name, container_type, metadata_json, notes, sort_order)
SELECT 'Unassigned', 'bin', '{}', 'Fallback container for imported or unplaced stock', 0
WHERE NOT EXISTS (
    SELECT 1 FROM storage_containers WHERE name = 'Unassigned'
);

INSERT INTO storage_slots (
    container_id, label, slot_type, ordinal, x1, y1, x2, y2, metadata_json, notes
)
SELECT sc.id, 'Main', 'bulk', 1, NULL, NULL, NULL, NULL, '{}', 'Default fallback slot'
FROM storage_containers sc
WHERE sc.name = 'Unassigned'
  AND NOT EXISTS (
      SELECT 1 FROM storage_slots ss
      WHERE ss.container_id = sc.id AND ss.label = 'Main'
  );

INSERT INTO part_locations (part_id, slot_id, qty, created_at, updated_at)
SELECT p.id, p.slot_id, p.qty, p.created_at, p.updated_at
FROM parts p
WHERE p.qty > 0
  AND p.slot_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM part_locations pl
      WHERE pl.part_id = p.id AND pl.slot_id = p.slot_id
  );

INSERT INTO part_locations (part_id, slot_id, qty, created_at, updated_at)
SELECT
    p.id,
    ss.id,
    p.qty,
    p.created_at,
    p.updated_at
FROM parts p
JOIN storage_containers sc ON sc.name = 'Unassigned'
JOIN storage_slots ss ON ss.container_id = sc.id AND ss.label = 'Main'
WHERE p.qty > 0
  AND p.slot_id IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM part_locations pl
      WHERE pl.part_id = p.id
  );

DROP VIEW IF EXISTS part_inventory_summary;

CREATE VIEW IF NOT EXISTS part_inventory_summary AS
SELECT
    p.id AS part_id,
    p.name AS name,
    p.category AS category,
    p.default_package AS default_package,
    p.supplier_sku AS supplier_sku,
    p.qty AS total_qty,
    COALESCE(
        (
            SELECT GROUP_CONCAT(loc.location_text, '; ')
            FROM (
                SELECT
                    sc.name || ' / ' || ss.label || ' (' || pl.qty || ')' AS location_text
                FROM part_locations pl
                JOIN storage_slots ss ON ss.id = pl.slot_id
                JOIN storage_containers sc ON sc.id = ss.container_id
                WHERE pl.part_id = p.id
                  AND pl.qty > 0
                ORDER BY
                    CASE WHEN sc.name = 'Unassigned' THEN 1 ELSE 0 END,
                    sc.name,
                    ss.label
            ) loc
        ),
        ''
    ) AS locations,
    p.notes AS notes
FROM parts p;

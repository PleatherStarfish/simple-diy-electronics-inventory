-- Move qty and slot_id from stock_lots onto the parts table directly,
-- then drop the stock_lots table and lot-based inventory view.

ALTER TABLE parts ADD COLUMN qty INTEGER NOT NULL DEFAULT 0;
ALTER TABLE parts ADD COLUMN slot_id INTEGER;

-- Migrate: sum lot quantities per part, pick the slot with the most stock
UPDATE parts SET
  qty = COALESCE((SELECT SUM(qty) FROM stock_lots WHERE part_id = parts.id), 0),
  slot_id = (SELECT slot_id FROM stock_lots WHERE part_id = parts.id ORDER BY qty DESC LIMIT 1);

DROP VIEW IF EXISTS part_inventory_summary;
DROP TABLE IF EXISTS stock_lots;

CREATE VIEW IF NOT EXISTS part_inventory_summary AS
SELECT
    p.id AS part_id,
    p.name AS name,
    p.category AS category,
    p.supplier_sku AS supplier_sku,
    p.qty AS total_qty,
    COALESCE(sc.name || ' / ' || ss.label, '') AS locations,
    p.notes AS notes
FROM parts p
LEFT JOIN storage_slots ss ON ss.id = p.slot_id
LEFT JOIN storage_containers sc ON sc.id = ss.container_id;

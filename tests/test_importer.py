from pathlib import Path

import pandas as pd

from eurorack_inventory.app import build_app_context


def test_importer_reads_spreadsheet_snapshot(tmp_path: Path) -> None:
    workbook = tmp_path / "inventory.xlsx"
    df = pd.DataFrame(
        [
            {"Category": "Resistors", "Component": "100k", "Total Qty": 50, "Tayda SKU": "R-100K", "Box Location": "", "Merged From": "100k x50"},
            {"Category": "ICs", "Component": "TL072", "Total Qty": 4, "Tayda SKU": "IC-TL072", "Box Location": "", "Merged From": "bag"},
            {"Category": "ICs", "Component": "CD40106", "Total Qty": "bad", "Tayda SKU": "IC-40106", "Box Location": "", "Merged From": "bad qty"},
        ]
    )
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Consolidated Inventory", index=False)

    context = build_app_context(tmp_path / "app.db")
    report = context.import_service.import_file(workbook, mode="replace_snapshot")
    context.search_service.rebuild()
    summaries = context.inventory_service.list_inventory()

    assert report.imported_parts == 2
    assert report.skipped_rows == 1
    assert report.warnings
    assert len(summaries) == 2

    # Verify qty is set directly on parts
    detail = context.inventory_service.get_part_detail(summaries[0].part_id)
    assert detail.part.qty > 0

    context.db.close()

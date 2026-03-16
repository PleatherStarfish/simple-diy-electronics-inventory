"""
BOM Extractor Service
Extracts raw BOM data from NLC PDF and CSV files.
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import unquote

import pandas as pd

from eurorack_inventory.domain.models import RawBomItem

logger = logging.getLogger(__name__)


def check_pdf_available() -> bool:
    """Check if tabula-py and Java are available for PDF extraction."""
    try:
        import tabula  # noqa: F401
    except ImportError:
        return False
    try:
        import subprocess

        result = subprocess.run(
            ["java", "-version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def file_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_module_name(name: str) -> str:
    """Clean up module name from filename or CSV _module column."""
    if not name:
        return ""
    name = unquote(name.replace("+", " "))
    for prefix in ["NLC - ", "NLC-", "NLC ", "nlc - ", "nlc-", "nlc "]:
        if name.lower().startswith(prefix.lower()):
            name = name[len(prefix) :]
    # Longest suffixes first to avoid partial matches
    for suffix in [
        " Build and BOM", " build and BOM", "_Build_and_BOM",
        "_build_and_bom", "_build_and",
        " BOM", " bom", "_BOM", "_bom",
    ]:
        if name.lower().endswith(suffix.lower()):
            name = name[: -len(suffix)]
            break
    name = name.replace("_", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name


# ── CSV Extraction ──────────────────────────────────────────────────────


def extract_csv(csv_path: Path) -> dict[str, list[RawBomItem]]:
    """
    Parse a combined NLC BOM CSV (from nlc_bom_extractor.py --combine).
    Returns {module_name: [RawBomItem, ...]}.

    Expected columns: _module, _source_file, VALUE, QUANTITY, DETAILS
    Also handles single-module CSVs without _module column.
    """
    df = pd.read_csv(csv_path)

    # Normalize column names to lowercase for matching
    col_map = {c: c.lower().strip() for c in df.columns}
    df = df.rename(columns=col_map)

    # Determine module column
    module_col = None
    for candidate in ["_module", "module"]:
        if candidate in df.columns:
            module_col = candidate
            break

    # Determine value/qty/details columns
    value_col = _find_col(df, ["value", "component", "part"])
    qty_col = _find_col(df, ["quantity", "qty"])
    details_col = _find_col(df, ["details", "notes", "description"])

    if value_col is None:
        logger.warning("No value column found in %s", csv_path)
        return {}

    result: dict[str, list[RawBomItem]] = {}

    for _, row in df.iterrows():
        if module_col:
            module_name = clean_module_name(str(row.get(module_col, "")))
        else:
            module_name = clean_module_name(csv_path.stem)

        if not module_name or module_name == "nan":
            continue

        value = str(row.get(value_col, "")).strip()
        if not value or value == "nan":
            continue

        qty_raw = str(row.get(qty_col, "")).strip() if qty_col else ""
        if qty_raw == "nan":
            qty_raw = ""

        details = str(row.get(details_col, "")).strip() if details_col else ""
        if details == "nan":
            details = ""

        if module_name not in result:
            result[module_name] = []

        line_number = len(result[module_name]) + 1
        result[module_name].append(
            RawBomItem(
                id=None,
                bom_source_id=0,  # will be set by caller
                line_number=line_number,
                raw_description=value,
                raw_qty=qty_raw,
                raw_reference=None,
                raw_supplier_pn=None,
                raw_notes=details if details else None,
            )
        )

    logger.info("Extracted %d modules from CSV %s", len(result), csv_path.name)
    return result


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    candidate_set = {candidate.strip().lower() for candidate in candidates}
    for column in df.columns:
        normalized = str(column).strip().lower()
        if normalized in candidate_set:
            return column
    return None


# ── PDF Extraction ──────────────────────────────────────────────────────


def extract_pdf(pdf_path: Path) -> list[RawBomItem]:
    """
    Extract BOM data from a single NLC PDF using tabula-py.
    Requires tabula-py and Java to be installed.
    """
    try:
        import tabula
    except ImportError:
        raise RuntimeError(
            "tabula-py is not installed. Install with: pip install tabula-py\n"
            "Also requires Java Runtime Environment."
        )

    tables = _extract_tables_from_pdf(pdf_path, tabula)
    raw_items: list[RawBomItem] = []
    line_number = 0
    cleaned_tables = 0
    normalized_tables = 0

    for table_index, df in enumerate(tables, start=1):
        try:
            cleaned, clean_reason = _clean_bom_dataframe_with_reason(df)
        except Exception as exc:
            logger.warning(
                "Skipping table %s in %s during cleaning: %s",
                table_index,
                pdf_path.name,
                exc,
            )
            continue
        if cleaned.empty:
            logger.info(
                "Skipping table %s in %s after cleaning: %s (shape=%s)",
                table_index,
                pdf_path.name,
                clean_reason,
                df.shape,
            )
            continue
        cleaned_tables += 1

        try:
            normalized, normalize_reason = _normalize_bom_table_with_reason(cleaned)
        except Exception as exc:
            logger.warning(
                "Skipping table %s in %s during normalization: %s",
                table_index,
                pdf_path.name,
                exc,
            )
            continue
        if normalized.empty:
            logger.info(
                "Skipping table %s in %s after normalization: %s (columns=%s)",
                table_index,
                pdf_path.name,
                normalize_reason,
                [str(column) for column in cleaned.columns],
            )
            continue
        normalized_tables += 1

        # Map to RawBomItems
        value_col = _find_col(normalized, ["value", "component"])
        qty_col = _find_col(normalized, ["quantity", "qty"])
        details_col = _find_col(normalized, ["details", "notes"])
        if value_col is None:
            logger.warning(
                "Skipping normalized table %s in %s: no value column found after normalization (columns=%s)",
                table_index,
                pdf_path.name,
                [str(column) for column in normalized.columns],
            )
            continue

        for _, row in normalized.iterrows():
            value = str(row.get(value_col, "")).strip() if value_col else ""
            if not value or value == "nan":
                continue

            line_number += 1
            qty_raw = str(row.get(qty_col, "")).strip() if qty_col else ""
            details = str(row.get(details_col, "")).strip() if details_col else ""

            raw_items.append(
                RawBomItem(
                    id=None,
                    bom_source_id=0,
                    line_number=line_number,
                    raw_description=value,
                    raw_qty=qty_raw if qty_raw != "nan" else "",
                    raw_reference=None,
                    raw_supplier_pn=None,
                    raw_notes=details if details and details != "nan" else None,
                )
            )

    log_level = logging.INFO if raw_items else logging.WARNING
    logger.log(
        log_level,
        "PDF extraction summary for %s: tables=%d, cleaned_tables=%d, normalized_tables=%d, raw_items=%d",
        pdf_path.name,
        len(tables),
        cleaned_tables,
        normalized_tables,
        len(raw_items),
    )
    return raw_items


def _extract_tables_from_pdf(pdf_path: Path, tabula) -> list[pd.DataFrame]:
    """Extract all tables from a PDF using Tabula."""
    try:
        tables = tabula.read_pdf(
            str(pdf_path), pages="all", lattice=True,
            pandas_options={"header": None},
        )
        if not tables or all(df.empty for df in tables):
            tables = tabula.read_pdf(
                str(pdf_path), pages="all", stream=True,
                pandas_options={"header": None},
            )
        return tables if tables else []
    except Exception as e:
        logger.warning("Error extracting from %s: %s", pdf_path.name, e)
        return []


def _clean_cell_value(value: str) -> str:
    if pd.isna(value) or value == "nan":
        return ""
    value = value.replace("\r", " ").replace("\n", " ")
    while "  " in value:
        value = value.replace("  ", " ")
    return value.strip()


def _clean_bom_dataframe(df: pd.DataFrame, min_cols: int = 2, min_rows: int = 3) -> pd.DataFrame:
    """Clean and normalize a BOM DataFrame."""
    cleaned, _reason = _clean_bom_dataframe_with_reason(df, min_cols=min_cols, min_rows=min_rows)
    return cleaned


def _clean_bom_dataframe_with_reason(
    df: pd.DataFrame,
    min_cols: int = 2,
    min_rows: int = 3,
) -> tuple[pd.DataFrame, str]:
    """Clean and normalize a BOM DataFrame and explain why it was skipped."""
    if df.empty:
        return df, "table was empty"

    df = df.dropna(how="all", axis=0).dropna(how="all", axis=1)
    if df.empty or len(df.columns) < min_cols or len(df) < min_rows:
        return pd.DataFrame(), "table was too small after removing blank rows and columns"

    header_keywords = [
        "qty", "quantity", "value", "part", "component", "ref", "reference",
        "designator", "description", "footprint", "package", "mouser", "digikey",
    ]

    header_row_idx = None
    for idx, row in df.iterrows():
        row_str = " ".join(str(v).lower() for v in row.values if pd.notna(v))
        if any(kw in row_str for kw in header_keywords):
            max_cell_len = max(len(str(v)) for v in row.values if pd.notna(v))
            has_newlines = any(
                "\r" in str(v) or "\n" in str(v)
                for v in row.values if pd.notna(v)
            )
            has_decimals = any(
                "." in str(v) and str(v).replace(".", "").isdigit()
                for v in row.values if pd.notna(v)
            )
            if max_cell_len < 50 and not has_newlines and not has_decimals:
                header_row_idx = idx
                break

    if header_row_idx is not None:
        new_headers = df.loc[header_row_idx].fillna("").astype(str).tolist()
        seen: dict[str, int] = {}
        unique_headers = []
        for h in new_headers:
            h = h.strip()
            if h in seen:
                seen[h] += 1
                unique_headers.append(f"{h}_{seen[h]}")
            else:
                seen[h] = 0
                unique_headers.append(h)
        df.columns = unique_headers
        df = df.loc[header_row_idx + 1 :].reset_index(drop=True)
    else:
        component_patterns = [
            "pF", "nF", "uF", "ohm", "k", "M", "pot", "socket", "jack",
            "connector", "LED", "TL0", "LM", "BC", "diode", "cap", "pin",
        ]
        first_col_samples = df.iloc[:, 0].astype(str).tolist()[:5]
        looks_like_bom = any(
            any(pat.lower() in str(val).lower() for pat in component_patterns)
            for val in first_col_samples
        )
        if looks_like_bom:
            if len(df.columns) == 2:
                df.columns = ["VALUE", "DETAILS"]
            elif len(df.columns) == 3:
                df.columns = ["VALUE", "QUANTITY", "DETAILS"]
            else:
                df.columns = ["VALUE", "QUANTITY", "DETAILS"] + [
                    f"col_{i}" for i in range(3, len(df.columns))
                ]
        else:
            return pd.DataFrame(), "table did not look like a BOM after header detection"

    df = df.loc[:, df.columns.astype(str).str.strip() != ""]
    if len(df) > 0:
        first_col = df.columns[0]
        df = df[~df[first_col].astype(str).str.lower().isin(header_keywords)]

    for col in df.columns:
        df[col] = df[col].astype(str).apply(_clean_cell_value)

    df = df[~df.apply(lambda row: all(v in ["", "nan"] for v in row), axis=1)]
    if df.empty:
        return pd.DataFrame(), "table had no data rows after cleanup"
    return df.reset_index(drop=True), ""


def _unpack_side_by_side_table(df: pd.DataFrame) -> pd.DataFrame:
    """Handle tables with side-by-side columns (component | qty | notes | component_1 | qty_1 | notes_1)."""
    base_cols = []
    suffix_groups: dict[int, list[tuple[str, str]]] = {}

    for col in df.columns:
        label = str(col)
        match = re.match(r"^(.+?)_(\d+)$", label)
        if match:
            suffix = int(match.group(2))
            if suffix not in suffix_groups:
                suffix_groups[suffix] = []
            suffix_groups[suffix].append((match.group(1), col))
        else:
            base_cols.append(col)

    if not suffix_groups:
        return df

    all_rows = []
    for _, row in df.iterrows():
        base_row = {col: row[col] for col in base_cols}
        if any(str(v).strip() and str(v) != "nan" for v in base_row.values()):
            all_rows.append(base_row)
        for suffix in sorted(suffix_groups.keys()):
            suffix_row = {}
            for base, full_col in suffix_groups[suffix]:
                suffix_row[base] = row[full_col]
            if any(str(v).strip() and str(v) != "nan" for v in suffix_row.values()):
                all_rows.append(suffix_row)

    return pd.DataFrame(all_rows) if all_rows else df


def _unpack_variant_table(df: pd.DataFrame) -> pd.DataFrame:
    """Handle variant-style BOMs (e.g. columns: designator | torpor | apathy | inertia)."""
    cols = list(df.columns)
    if len(df) == 0 or len(cols) <= 2:
        return df

    first_col_vals = df.iloc[:, 0].fillna("").tolist()
    designator_pattern = re.compile(r"^[A-Z]+\d+$", re.I)
    designator_count = sum(
        1 for v in first_col_vals if designator_pattern.match(str(v).strip())
    )

    if designator_count <= len(first_col_vals) * 0.5:
        return df

    all_rows = []
    variant_cols = cols[1:]
    for _, row in df.iterrows():
        designator = str(row.iloc[0])
        for variant_col in variant_cols:
            value = str(row[variant_col])
            if value and value.lower() not in ["nan", "", "nothing!"]:
                all_rows.append({
                    "VALUE": value,
                    "QUANTITY": "1",
                    "DETAILS": f"Designator: {designator}, Variant: {str(variant_col)}",
                })

    return pd.DataFrame(all_rows) if all_rows else df


def _normalize_bom_table(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize various BOM formats to standard VALUE/QUANTITY/DETAILS structure."""
    normalized, _reason = _normalize_bom_table_with_reason(df)
    return normalized


def _normalize_bom_table_with_reason(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Normalize various BOM formats to standard VALUE/QUANTITY/DETAILS structure."""
    df = _unpack_side_by_side_table(df)
    df = _unpack_variant_table(df)

    column_mapping = {}
    for col in df.columns:
        col_lower = str(col).lower().strip()
        if col_lower in ["value", "component", "part", "item"]:
            column_mapping[col] = "VALUE"
        elif col_lower in ["quantity", "qty", "count", "amount"]:
            column_mapping[col] = "QUANTITY"
        elif col_lower in ["details", "notes", "description", "info", "comments"]:
            column_mapping[col] = "DETAILS"

    if column_mapping:
        df = df.rename(columns=column_mapping)

    for std_col in ["VALUE", "QUANTITY", "DETAILS"]:
        if std_col not in df.columns:
            df[std_col] = ""

    std_cols = ["VALUE", "QUANTITY", "DETAILS"]
    other_cols = [c for c in df.columns if c not in std_cols]
    df = df[std_cols + other_cols]

    if df["VALUE"].astype(str).str.strip().eq("").all() or df["VALUE"].isna().all():
        for col in other_cols:
            if not df[col].astype(str).str.strip().eq("").all():
                df["VALUE"] = df[col]
                df = df.drop(columns=[col])
                break

    df = df[df["VALUE"].astype(str).str.strip().ne("")]
    df = df[df["VALUE"].astype(str).ne("nan")]
    if df.empty:
        return pd.DataFrame(), "normalization left no usable VALUE rows"
    return df, ""

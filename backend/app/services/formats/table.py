"""临床表格规范化：CSV/TSV/XLSX/Parquet/JSON -> Parquet。"""

from __future__ import annotations

import csv
import io
import json
import shutil
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

TABLE_SUFFIXES = {".csv", ".tsv", ".xlsx", ".parquet", ".json"}
TABLE_MEDIA_TYPE = "application/vnd.apache.parquet"


@dataclass
class TableSheet:
    name: str
    table: pa.Table


def is_table_file(path: Path) -> bool:
    return path.suffix.lower() in TABLE_SUFFIXES


def _clean_headers(values: Iterable[Any]) -> list[str]:
    headers: list[str] = []
    seen: dict[str, int] = {}
    for index, value in enumerate(values):
        name = str(value).strip() if value is not None else ""
        if not name:
            name = f"column_{index + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        headers.append(name)
    return headers


def _rows_to_table(headers: list[str], rows: list[list[Any]]) -> pa.Table:
    records: list[dict[str, Any]] = []
    for row in rows:
        if not any(value not in (None, "") for value in row):
            continue
        padded = list(row) + [None] * max(0, len(headers) - len(row))
        records.append(
            {
                header: _json_safe_value(padded[index]) if index < len(padded) else None
                for index, header in enumerate(headers)
            }
        )
    return pa.Table.from_pylist(records) if records else pa.table({h: [] for h in headers})


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _read_csv(path: Path) -> TableSheet:
    raw = path.read_bytes()
    text: str | None = None
    encoding_used = ""
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            text = raw.decode(encoding)
            encoding_used = encoding
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError(f"无法识别 CSV 编码：{path.name}")

    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    if delimiter == ",":
        with suppress(csv.Error):
            delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t").delimiter

    if encoding_used in ("utf-8-sig", "utf-8"):
        try:
            parse_options = pacsv.ParseOptions(delimiter=delimiter)
            table = pacsv.read_csv(io.BytesIO(text.encode("utf-8")), parse_options=parse_options)
            return TableSheet(name=path.stem, table=table)
        except Exception:  # noqa: BLE001 - 退化到 Python csv，保证兼容不规则文件
            pass

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        headers = _clean_headers(next(reader))
    except StopIteration as exc:
        raise ValueError(f"表格为空：{path.name}") from exc
    rows = [row for row in reader]
    return TableSheet(name=path.stem, table=_rows_to_table(headers, rows))


def _read_xlsx(path: Path) -> list[TableSheet]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - 依赖缺失时给出明确提示
        raise ValueError("读取 XLSX 需要安装 openpyxl") from exc

    workbook = load_workbook(path, read_only=True, data_only=True)
    sheets: list[TableSheet] = []
    try:
        for worksheet in workbook.worksheets:
            rows_iter = worksheet.iter_rows(values_only=True)
            try:
                headers = _clean_headers(next(rows_iter))
            except StopIteration:
                continue
            rows = [list(row) for row in rows_iter]
            if not rows:
                continue
            sheets.append(TableSheet(name=worksheet.title, table=_rows_to_table(headers, rows)))
    finally:
        workbook.close()
    if not sheets:
        raise ValueError(f"表格中没有可导入的数据：{path.name}")
    return sheets


def _normalize_parquet(
    path: Path, out_dir: Path
) -> list[tuple[str, Path, dict[str, Any], dict[str, Any]]]:
    """Parquet 已是规范格式，直接复制，避免大表全量读入内存。"""

    out_path = out_dir / f"{path.stem}.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, out_path)
    parquet = pq.ParquetFile(path)
    columns = [{"name": field.name, "type": str(field.type)} for field in parquet.schema_arrow]
    geometry = {
        "row_count": int(parquet.metadata.num_rows),
        "column_count": len(columns),
        "columns": columns,
    }
    metadata = {
        "source_format": "parquet",
        "sheet_name": path.stem,
        "row_count": int(parquet.metadata.num_rows),
        "column_count": len(columns),
        "columns": columns,
    }
    return [(path.stem, out_path, geometry, metadata)]


def _read_json(path: Path) -> TableSheet:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        for key in ("rows", "data", "records"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list) or not payload:
        raise ValueError("JSON 表格必须是对象数组，或包含 rows/data/records 数组")
    if not all(isinstance(item, dict) for item in payload):
        raise ValueError("JSON 表格的每一行必须是对象")
    headers = _clean_headers(payload[0].keys())
    normalized = [
        {header: _json_safe_value(item.get(header)) for header in headers} for item in payload
    ]
    return TableSheet(name=path.stem, table=pa.Table.from_pylist(normalized))


def normalize_table(
    path: Path, out_dir: Path
) -> list[tuple[str, Path, dict[str, Any], dict[str, Any]]]:
    """把表格文件规范化为 Parquet。

    返回 [(sheet_name, parquet_path, geometry, metadata)]；XLSX 的每个 sheet
    对应一个 Case，其余格式一个文件对应一个 Case。
    """

    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return _normalize_parquet(path, out_dir)
    if suffix in (".csv", ".tsv"):
        sheets = [_read_csv(path)]
    elif suffix == ".xlsx":
        sheets = _read_xlsx(path)
    elif suffix == ".json":
        sheets = [_read_json(path)]
    else:
        raise ValueError(f"不支持的表格格式：{suffix}")

    results: list[tuple[str, Path, dict[str, Any], dict[str, Any]]] = []
    for sheet in sheets:
        safe_sheet = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in sheet.name).strip(
            "._"
        )
        safe_sheet = safe_sheet or "sheet"
        out_path = out_dir / f"{safe_sheet}.parquet"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(sheet.table, out_path, compression="snappy")
        columns = [{"name": field.name, "type": str(field.type)} for field in sheet.table.schema]
        geometry = {
            "row_count": int(sheet.table.num_rows),
            "column_count": int(sheet.table.num_columns),
            "columns": columns,
        }
        metadata = {
            "source_format": suffix.lstrip("."),
            "sheet_name": sheet.name,
            "row_count": int(sheet.table.num_rows),
            "column_count": int(sheet.table.num_columns),
            "columns": columns,
        }
        results.append((sheet.name, out_path, geometry, metadata))
    return results


def table_info(path: str | Path) -> dict[str, Any]:
    parquet = pq.ParquetFile(path)
    columns = [{"name": field.name, "type": str(field.type)} for field in parquet.schema_arrow]
    return {
        "row_count": int(parquet.metadata.num_rows),
        "column_count": len(columns),
        "columns": columns,
    }


def read_table_page(path: str | Path, offset: int = 0, limit: int = 100) -> dict[str, Any]:
    parquet = pq.ParquetFile(path)
    total = int(parquet.metadata.num_rows)
    table = parquet.read().slice(max(0, offset), max(1, min(limit, 500)))
    columns = [field.name for field in table.schema]
    rows: list[list[Any]] = []
    for record in table.to_pylist():
        rows.append([_json_safe_value(record.get(column)) for column in columns])
    return {
        "total": total,
        "row_count": total,
        "column_count": len(columns),
        "offset": max(0, offset),
        "limit": max(1, min(limit, 500)),
        "columns": [{"name": field.name, "type": str(field.type)} for field in table.schema],
        "rows": rows,
    }

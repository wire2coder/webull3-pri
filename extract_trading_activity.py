from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple


try:
    import pandas as pd
    import pdfplumber
except ModuleNotFoundError as exc:
    missing = str(exc).split("'")[1] if "'" in str(exc) else str(exc)
    print(
        f"Missing dependency: {missing}. Install requirements with: pip install pandas pdfplumber",
        file=sys.stderr,
    )
    raise


LOGGER = logging.getLogger("extract_trading_activity")

REQUIRED_COLUMNS = [
    "Symbol & Name",
    "Cusip",
    "Trade Date",
    "Settlement Date",
    "Account Type",
    "Buy/Sell",
    "Quantity",
    "Price",
    "Gross Amount",
    "Commission",
    "Fee/Tax",
    "Net Amount",
    "MKT",
    "Solicitation",
    "CAP",
    "Overnight Trade",
    "Algorithm",
    "Callable",
]


def _to_json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _to_json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(_to_json_safe(payload), handle, indent=2)


def _normalize_text(value: str) -> str:
    normalized = re.sub(r"\s+", " ", (value or "").strip().upper())
    normalized = re.sub(r"\s*/\s*", "/", normalized)
    return normalized


def _parse_numeric(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace("(", "-", regex=False)
        .str.replace(")", "", regex=False)
        .str.strip()
    )
    cleaned = cleaned.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    return pd.to_numeric(cleaned, errors="coerce")


def extract_trading_activity_table(
    pdf_path: Path,
    out_csv: Path,
    start_marker: str,
    end_marker: str,
    strict: bool,
    max_malformed_rows: int,
    min_completeness: float,
) -> Tuple[pd.DataFrame, Dict[str, object]]:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    start_norm = _normalize_text(start_marker)
    end_norm = _normalize_text(end_marker)
    required_columns_norm = [_normalize_text(col) for col in REQUIRED_COLUMNS]

    page_texts = []
    with pdfplumber.open(str(pdf_path)) as doc:
        for page_num, page in enumerate(doc.pages, start=1):
            text = page.extract_text() or ""
            page_texts.append((page_num, _normalize_text(text)))

        start_pages = [page for page, normalized_text in page_texts if start_norm in normalized_text]
        end_pages = [page for page, normalized_text in page_texts if end_norm in normalized_text]

        if not start_pages:
            raise ValueError(f"Start marker not found: {start_marker}")
        if not end_pages:
            raise ValueError(f"End marker not found: {end_marker}")

        start_page = min(start_pages)
        end_page_candidates = [page for page in end_pages if page >= start_page]
        if not end_page_candidates:
            raise ValueError(
                f"End marker appears before start marker (start page {start_page}, end pages {end_pages})"
            )
        end_page = min(end_page_candidates)

        candidate_tables = []
        for page in doc.pages[start_page - 1 : end_page]:
            page_num = page.page_number
            tables = page.extract_tables() or []
            for table_index, table in enumerate(tables, start=1):
                if not table or len(table) < 2:
                    continue

                header_norm = [_normalize_text(str(cell)) for cell in table[0]]
                matched_required = sum(
                    1 for required in required_columns_norm if any(required == header for header in header_norm)
                )

                row_lengths = [len(row) for row in table if row]
                max_cols = max(row_lengths) if row_lengths else 0

                candidate_tables.append(
                    {
                        "page": page_num,
                        "table_index": table_index,
                        "table": table,
                        "matched_required": matched_required,
                        "max_cols": max_cols,
                    }
                )

    if not candidate_tables:
        raise RuntimeError(f"No tables found between markers on pages {start_page} to {end_page}.")

    candidate_tables.sort(
        key=lambda item: (item["matched_required"], item["max_cols"], len(item["table"])),
        reverse=True,
    )
    chosen = candidate_tables[0]
    chosen_table = chosen["table"]
    chosen_page = chosen["page"]

    if chosen["matched_required"] < 10:
        raise RuntimeError(
            "Could not confidently identify the trading activity table: "
            f"only matched {chosen['matched_required']} required columns."
        )

    header = [str(cell).strip() for cell in chosen_table[0]]
    n_cols = len(header)

    # Keep all matching tables in-page order so multi-page sections are merged.
    ordered_candidates = sorted(candidate_tables, key=lambda item: (item["page"], item["table_index"]))

    selected_tables: List[Dict[str, object]] = []
    for candidate in ordered_candidates:
        include = False
        if int(candidate["matched_required"]) >= 10:
            include = True
        else:
            # Some page breaks produce continuation tables without a repeated header.
            if (
                int(candidate["page"]) > chosen_page
                and max(1, n_cols - 1) <= int(candidate["max_cols"]) <= n_cols + 1
            ):
                include = True
        if include:
            selected_tables.append(candidate)

    if not selected_tables:
        selected_tables = [chosen]

    malformed_rows = 0
    cleaned_rows = []
    selected_pages = sorted({int(item["page"]) for item in selected_tables})
    best_header_match = max(int(item["matched_required"]) for item in selected_tables)
    for candidate in selected_tables:
        table = candidate["table"]
        start_index = 1 if int(candidate["matched_required"]) >= 10 else 0
        for row in table[start_index:]:
            row = row or []
            if len(row) != n_cols:
                malformed_rows += 1
            if len(row) < n_cols:
                row = row + [None] * (n_cols - len(row))
            elif len(row) > n_cols:
                row = row[:n_cols]
            cleaned_rows.append(row)

    if strict and malformed_rows > max_malformed_rows:
        raise RuntimeError(f"Malformed rows detected: {malformed_rows} (allowed: {max_malformed_rows}).")

    df = pd.DataFrame(cleaned_rows, columns=header)

    for col in df.columns:
        df[col] = df[col].map(lambda value: value.replace("\n", " ").strip() if isinstance(value, str) else value)

    df.replace("", pd.NA, inplace=True)
    df.dropna(axis=0, how="all", inplace=True)
    df.dropna(axis=1, how="all", inplace=True)
    df.reset_index(drop=True, inplace=True)

    if df.empty:
        raise RuntimeError("Extracted table is empty after cleanup.")

    normalized_df_cols = [_normalize_text(col) for col in df.columns]
    norm_to_original = {norm: original for norm, original in zip(normalized_df_cols, df.columns)}

    for req_display in REQUIRED_COLUMNS:
        req_norm = _normalize_text(req_display)
        if req_norm in norm_to_original:
            src_col = norm_to_original[req_norm]
            if src_col != req_display:
                df.rename(columns={src_col: req_display}, inplace=True)
        else:
            df[req_display] = pd.NA

    ordered_cols = REQUIRED_COLUMNS + [col for col in df.columns if col not in REQUIRED_COLUMNS]
    df = df[ordered_cols]

    normalized_df_cols = [_normalize_text(col) for col in df.columns]
    missing_required = [req for req in required_columns_norm if req not in normalized_df_cols]
    if strict and missing_required:
        raise RuntimeError("Missing expected columns after extraction: " + ", ".join(missing_required))

    total_cells = df.shape[0] * df.shape[1]
    non_null_cells = int(df.notna().sum().sum())
    completeness = non_null_cells / total_cells if total_cells else 0.0

    if strict and completeness < min_completeness:
        raise RuntimeError(
            f"Table completeness too low: {completeness:.2%} < {min_completeness:.2%}"
        )

    if strict:
        for req in REQUIRED_COLUMNS:
            if df[req].isna().all() and req not in ("Callable", "Cusip"):
                raise RuntimeError(f"Required column has no values: {req}")

    numeric_totals: Dict[str, float] = {}
    total_targets = {
        "quantity_total": "Quantity",
        "gross_amount_total": "Gross Amount",
        "net_amount_total": "Net Amount",
    }
    for total_key, target_col in total_targets.items():
        if target_col in df.columns:
            numeric_totals[total_key] = float(_parse_numeric(df[target_col]).sum(skipna=True))

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)

    qa_report = {
        "saved_file": str(out_csv),
        "source_page": int(chosen_page),
        "source_pages": selected_pages,
        "shape": (int(df.shape[0]), int(df.shape[1])),
        "malformed_rows": int(malformed_rows),
        "completeness": round(float(completeness), 4),
        "matched_required_columns": int(best_header_match),
        "numeric_totals": numeric_totals,
    }
    return df, qa_report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract the 'Securities Trading Activity' table from a statement PDF."
    )
    parser.add_argument(
        "--pdf",
        help="Input PDF filename or full path. If omitted, --date is used.",
    )
    parser.add_argument(
        "--date",
        help="Date stem for PDF name (example: 2026-04-01 -> 2026-04-01.pdf).",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process all matching PDFs in input directory and create a combined summary CSV.",
    )
    parser.add_argument(
        "--pdf-glob",
        default="*.pdf",
        help="Glob pattern for PDF discovery in batch mode. Default: *.pdf",
    )
    parser.add_argument(
        "--batch-summary-csv",
        default="trading_activity_batch_summary.csv",
        help="Filename for batch summary CSV in output directory.",
    )
    parser.add_argument(
        "--input-dir",
        default=".",
        help="Directory containing source PDFs. Default: current directory.",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory for generated CSV output. Default: current directory.",
    )
    parser.add_argument(
        "--start-marker",
        default="SECURITIES TRADING ACTIVITY",
        help="Start section marker.",
    )
    parser.add_argument(
        "--end-marker",
        default="TRADING SUMMARY",
        help="End section marker.",
    )
    parser.add_argument(
        "--max-malformed-rows",
        type=int,
        default=0,
        help="Max malformed rows allowed in strict mode.",
    )
    parser.add_argument(
        "--min-completeness",
        type=float,
        default=0.70,
        help="Minimum non-null table completeness in strict mode (0.0-1.0).",
    )
    parser.add_argument(
        "--non-strict",
        action="store_true",
        help="Disable strict QA checks.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    parser.add_argument(
        "--no-qa-json",
        action="store_true",
        help="Disable writing JSON QA reports.",
    )
    parser.add_argument(
        "--qa-dir",
        default=None,
        help="Directory for QA JSON files. Default: output directory.",
    )
    return parser.parse_args()


def _resolve_pdf_path(args: argparse.Namespace) -> Path:
    input_dir = Path(args.input_dir)

    if args.pdf:
        pdf_candidate = Path(args.pdf)
        if not pdf_candidate.suffix:
            pdf_candidate = pdf_candidate.with_suffix(".pdf")
        if not pdf_candidate.is_absolute():
            pdf_candidate = input_dir / pdf_candidate
        return pdf_candidate

    if args.date:
        return input_dir / f"{args.date}.pdf"

    raise ValueError("Provide either --pdf or --date.")


def _resolve_batch_pdf_paths(args: argparse.Namespace) -> List[Path]:
    input_dir = Path(args.input_dir)
    paths = sorted(input_dir.glob(args.pdf_glob))
    return [path for path in paths if path.is_file()]


def _run_single(args: argparse.Namespace, pdf_path: Path) -> Tuple[pd.DataFrame, Dict[str, object]]:
    out_dir = Path(args.output_dir)
    qa_dir = Path(args.qa_dir) if args.qa_dir else out_dir

    out_csv = out_dir / f"{pdf_path.stem}_securities_trading_activity_table.csv"
    qa_json_path = qa_dir / f"{pdf_path.stem}_trading_activity_qa.json"

    LOGGER.info("Input PDF: %s", pdf_path)
    LOGGER.info("Output CSV: %s", out_csv)

    df, qa_report = extract_trading_activity_table(
        pdf_path=pdf_path,
        out_csv=out_csv,
        start_marker=args.start_marker,
        end_marker=args.end_marker,
        strict=not args.non_strict,
        max_malformed_rows=args.max_malformed_rows,
        min_completeness=args.min_completeness,
    )

    qa_report["source_pdf"] = str(pdf_path)
    qa_report["strict_mode"] = bool(not args.non_strict)

    if not args.no_qa_json:
        _write_json(qa_json_path, qa_report)
        qa_report["qa_json_file"] = str(qa_json_path)
        LOGGER.info("QA JSON: %s", qa_json_path)

    LOGGER.info("Saved: %s", qa_report["saved_file"])
    LOGGER.info("Source page: %s", qa_report["source_page"])
    if qa_report.get("source_pages"):
        LOGGER.info("Source pages: %s", qa_report["source_pages"])
    rows, cols = qa_report["shape"]
    LOGGER.info("Shape: %s rows x %s cols", rows, cols)
    LOGGER.info("Malformed rows: %s", qa_report["malformed_rows"])
    LOGGER.info("Completeness: %.2f%%", qa_report["completeness"] * 100)
    LOGGER.info("Matched required columns: %s", qa_report["matched_required_columns"])
    if qa_report["numeric_totals"]:
        LOGGER.info("Numeric totals: %s", qa_report["numeric_totals"])

    return df, qa_report


def parse_single_tradeconfirmation_pdf(
    pdf_name: str | None = None,
    tradeconfirmation_dir: Path | str = "tradeconfirmation",
    output_dir: Path | str = ".",
    start_marker: str = "SECURITIES TRADING ACTIVITY",
    end_marker: str = "TRADING SUMMARY",
    strict: bool = True,
    max_malformed_rows: int = 0,
    min_completeness: float = 0.70,
    write_qa_json: bool = True,
    qa_dir: Path | str | None = None,
) -> Tuple[pd.DataFrame, Dict[str, object]]:
    """Parse one PDF from the tradeconfirmation folder and write CSV/QA outputs.

    If pdf_name is omitted, this function requires exactly one PDF in the folder.
    """
    source_dir = Path(tradeconfirmation_dir)
    if not source_dir.exists():
        raise FileNotFoundError(f"tradeconfirmation folder not found: {source_dir}")

    if pdf_name:
        pdf_path = source_dir / pdf_name
        if pdf_path.suffix.lower() != ".pdf":
            pdf_path = pdf_path.with_suffix(".pdf")
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found in tradeconfirmation folder: {pdf_path}")
    else:
        pdf_files = sorted(path for path in source_dir.glob("*.pdf") if path.is_file())
        if len(pdf_files) == 0:
            raise FileNotFoundError(f"No PDF files found in {source_dir}")
        if len(pdf_files) > 1:
            names = ", ".join(path.name for path in pdf_files)
            raise ValueError(
                "Found multiple PDFs in tradeconfirmation folder; provide pdf_name explicitly. "
                f"Files: {names}"
            )
        pdf_path = pdf_files[0]

    out_dir = Path(output_dir)
    qa_output_dir = Path(qa_dir) if qa_dir else out_dir

    out_csv = out_dir / f"{pdf_path.stem}_securities_trading_activity_table.csv"
    qa_json_path = qa_output_dir / f"{pdf_path.stem}_trading_activity_qa.json"

    df, qa_report = extract_trading_activity_table(
        pdf_path=pdf_path,
        out_csv=out_csv,
        start_marker=start_marker,
        end_marker=end_marker,
        strict=strict,
        max_malformed_rows=max_malformed_rows,
        min_completeness=min_completeness,
    )

    qa_report["source_pdf"] = str(pdf_path)
    qa_report["strict_mode"] = bool(strict)
    if write_qa_json:
        _write_json(qa_json_path, qa_report)
        qa_report["qa_json_file"] = str(qa_json_path)

    return df, qa_report


def _run_batch(args: argparse.Namespace) -> int:
    pdf_paths = _resolve_batch_pdf_paths(args)
    if not pdf_paths:
        LOGGER.error("No PDF files found for batch mode using pattern: %s", args.pdf_glob)
        return 1

    LOGGER.info("Batch mode: found %s PDF(s)", len(pdf_paths))

    summary_rows: List[Dict[str, object]] = []
    failures = 0

    for pdf_path in pdf_paths:
        try:
            _, qa = _run_single(args, pdf_path)
            totals = qa.get("numeric_totals", {}) if isinstance(qa.get("numeric_totals", {}), dict) else {}
            rows, cols = qa["shape"]
            summary_rows.append(
                {
                    "pdf": str(pdf_path),
                    "status": "success",
                    "output_csv": qa["saved_file"],
                    "qa_json_file": qa.get("qa_json_file", ""),
                    "source_page": qa["source_page"],
                    "source_pages": ",".join(str(page) for page in qa.get("source_pages", [])),
                    "rows": rows,
                    "cols": cols,
                    "completeness": qa["completeness"],
                    "malformed_rows": qa["malformed_rows"],
                    "matched_required_columns": qa["matched_required_columns"],
                    "quantity_total": totals.get("quantity_total"),
                    "gross_amount_total": totals.get("gross_amount_total"),
                    "net_amount_total": totals.get("net_amount_total"),
                    "error": "",
                }
            )
        except Exception as exc:
            failures += 1
            LOGGER.error("Failed for %s: %s", pdf_path, exc)
            summary_rows.append(
                {
                    "pdf": str(pdf_path),
                    "status": "failed",
                    "output_csv": "",
                    "qa_json_file": "",
                    "source_page": "",
                    "source_pages": "",
                    "rows": "",
                    "cols": "",
                    "completeness": "",
                    "malformed_rows": "",
                    "matched_required_columns": "",
                    "quantity_total": "",
                    "gross_amount_total": "",
                    "net_amount_total": "",
                    "error": str(exc),
                }
            )

    summary_df = pd.DataFrame(summary_rows)
    summary_path = Path(args.output_dir) / args.batch_summary_csv
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(summary_path, index=False)
    LOGGER.info("Batch summary CSV: %s", summary_path)

    if not args.no_qa_json:
        batch_qa_json = Path(args.qa_dir) / "batch_run_qa.json" if args.qa_dir else Path(args.output_dir) / "batch_run_qa.json"
        batch_payload: Dict[str, object] = {
            "pdf_count": len(pdf_paths),
            "success_count": len(pdf_paths) - failures,
            "failure_count": failures,
            "summary_csv": str(summary_path),
            "items": summary_rows,
        }
        _write_json(batch_qa_json, batch_payload)
        LOGGER.info("Batch QA JSON: %s", batch_qa_json)

    return 0 if failures == 0 else 2


def main() -> int:
    args = _parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s: %(message)s")

    try:
        if args.batch:
            return _run_batch(args)

        pdf_path = _resolve_pdf_path(args)
        df, _ = _run_single(args, pdf_path)
        print(df[REQUIRED_COLUMNS].head(5).to_string(index=False))
        return 0
    except Exception as exc:
        LOGGER.error("Extraction failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
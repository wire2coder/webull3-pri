from __future__ import annotations

import argparse
import logging
from pathlib import Path

from extract_trading_activity import REQUIRED_COLUMNS, parse_single_tradeconfirmation_pdf


LOGGER = logging.getLogger("parse_tradeconfirmation_single")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse one trade confirmation PDF and extract the Securities Trading Activity table."
    )
    parser.add_argument(
        "--pdf",
        default=None,
        help="PDF filename inside tradeconfirmation folder (with or without .pdf).",
    )
    parser.add_argument(
        "--tradeconfirmation-dir",
        default="tradeconfirmation",
        help="Directory containing trade confirmation PDFs. Default: tradeconfirmation",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory for generated CSV output. Default: current directory.",
    )
    parser.add_argument(
        "--qa-dir",
        default=None,
        help="Directory for QA JSON output. Default: output directory.",
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
        "--no-qa-json",
        action="store_true",
        help="Disable writing per-run QA JSON.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s: %(message)s")

    try:
        df, qa_report = parse_single_tradeconfirmation_pdf(
            pdf_name=args.pdf,
            tradeconfirmation_dir=Path(args.tradeconfirmation_dir),
            output_dir=Path(args.output_dir),
            start_marker=args.start_marker,
            end_marker=args.end_marker,
            strict=not args.non_strict,
            max_malformed_rows=args.max_malformed_rows,
            min_completeness=args.min_completeness,
            write_qa_json=not args.no_qa_json,
            qa_dir=Path(args.qa_dir) if args.qa_dir else None,
        )

        LOGGER.info("Source PDF: %s", qa_report.get("source_pdf"))
        LOGGER.info("Output CSV: %s", qa_report.get("saved_file"))
        if qa_report.get("source_pages"):
            LOGGER.info("Source pages: %s", qa_report.get("source_pages"))
        if qa_report.get("qa_json_file"):
            LOGGER.info("QA JSON: %s", qa_report.get("qa_json_file"))

        rows, cols = qa_report["shape"]
        LOGGER.info("Shape: %s rows x %s cols", rows, cols)
        LOGGER.info("Completeness: %.2f%%", qa_report["completeness"] * 100)
        LOGGER.info("Matched required columns: %s", qa_report["matched_required_columns"])

        print(df[REQUIRED_COLUMNS].head(5).to_string(index=False))
        return 0
    except Exception as exc:
        LOGGER.error("Single tradeconfirmation extraction failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

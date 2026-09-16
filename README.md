# Trading Activity Extractor

Standalone CLI tool to extract the **Securities Trading Activity** table from statement PDFs and produce:
- Per-PDF CSV output
- Per-run QA JSON output
- Batch summary CSV and batch QA JSON (in batch mode)

Includes a dedicated standalone runner for **one PDF in the `tradeconfirmation` folder**.

## What is `py` on Windows?

`py` is the Python Launcher for Windows.
- `py` runs your default Python installation.
- `py -3` forces Python 3.
- `py -3.11` forces Python 3.11.

If you prefer, you can replace `py -3` with `python` in all commands, as long as `python` points to your intended interpreter.

## 1) Install dependencies

Windows:

```powershell
py -3 -m pip install -r requirements.txt
```

macOS / Linux:

```bash
python3 -m pip install -r requirements.txt
```

## 2) Run one PDF (by date)

```powershell
py -3 extract_trading_activity.py --date 2026-04-01 --input-dir . --output-dir .
```

## 3) Run one PDF (by filename)

```powershell
py -3 extract_trading_activity.py --pdf 2026-04-07.pdf --input-dir . --output-dir .
```

## 3b) Run one PDF from tradeconfirmation folder (standalone)

If there is exactly one PDF in `tradeconfirmation`, run:

```powershell
py -3 parse_tradeconfirmation_single.py --tradeconfirmation-dir .\tradeconfirmation --output-dir .\outputfolder
```

If there are multiple PDFs in `tradeconfirmation`, specify the file:

```powershell
py -3 parse_tradeconfirmation_single.py --tradeconfirmation-dir .\tradeconfirmation --pdf 2026-04-07.pdf --output-dir .\outputfolder
```

macOS / Linux:

```bash
python3 parse_tradeconfirmation_single.py --tradeconfirmation-dir ./tradeconfirmation --output-dir ./outputfolder
```

After a successful single-PDF parse, the source PDF is moved automatically to
`done1`, and parser messages are appended to `parse_tradeconfirmation.log` there.

## 3c) Required folders

- `wait1` — PDFs waiting to be processed
- `tradeconfirmation` — drop one PDF here to parse (single-file runner)
- `outputfolder` — CSV and QA JSON output
- `done1` — processed PDFs and single-run parser logs

The move scripts create `tradeconfirmation` and `done1` if they are missing.

## 3d) Count files in tradeconfirmation and move them to done1

Use the move scripts for files that were not processed by the single-PDF runner.

macOS / Linux:

```bash
./move_to_done1.sh
```

Windows 11 (PowerShell):

```powershell
.\move_to_done1.ps1
```

## 4) Run all PDFs in batch mode

```powershell
py -3 extract_trading_activity.py --batch --input-dir . --output-dir .
```

## 5) Batch mode with custom PDF filter

```powershell
py -3 extract_trading_activity.py --batch --pdf-glob "2026-04-*.pdf" --input-dir . --output-dir .
```

## 6) Optional: custom QA output directory

```powershell
py -3 extract_trading_activity.py --batch --input-dir . --output-dir . --qa-dir .\qa_reports
```

## 7) Optional: disable QA JSON files

```powershell
py -3 extract_trading_activity.py --batch --input-dir . --output-dir . --no-qa-json
```

## Troubleshooting: strict QA errors for Buy/Sell or Fee/Tax

Some statements format column headers with spaces around slashes (example: "Buy /Sell", "Fee /Tax").
The parser normalizes whitespace around slashes so these still map to the required
`Buy/Sell` and `Fee/Tax` columns. If strict mode errors persist, run once with
`--non-strict` to inspect the CSV output and confirm where the values landed.

## About Zone.Identifier files (Windows "Mark of the Web")

When you download a PDF statement from the Webull Tax Center (`https://www.webull.com/center/tax`)
using a Windows browser, Windows automatically attaches a hidden alternate data stream to the file
called `Zone.Identifier`. This stream contains:

```
[ZoneTransfer]
ZoneId=3
ReferrerUrl=https://www.webull.com/center/tax
HostUrl=https://ustrade-edoc.webullfinance.com/edoc/v1/...
```

- **ZoneId=3** means "Internet Zone" — i.e. the file was downloaded from the web
- This is a built-in Windows security feature ("Mark of the Web") that warns you before opening
  downloaded files
- On WSL/Linux, you may see the original download URL embedded in the file metadata
- This tool **does not** generate Zone.Identifier data — it only processes the PDF content

## Generated files

Single run creates:
- `<date>_securities_trading_activity_table.csv`
- `<date>_trading_activity_qa.json` (unless `--no-qa-json`)

Single run from `tradeconfirmation` creates in `outputfolder`:
- `<pdf_stem>_securities_trading_activity_table.csv`
- `<pdf_stem>_trading_activity_qa.json` (unless `--no-qa-json`)

Batch run creates:
- One CSV per PDF: `<date>_securities_trading_activity_table.csv`
- One QA JSON per PDF: `<date>_trading_activity_qa.json` (unless `--no-qa-json`)
- `trading_activity_batch_summary.csv`
- `batch_run_qa.json` (unless `--no-qa-json`)

## Quick verification commands

```powershell
# Verify summary artifacts from batch run
$f = @('trading_activity_batch_summary.csv','batch_run_qa.json')
$f | ForEach-Object { [pscustomobject]@{File=$_; Exists=(Test-Path $_); SizeBytes=((Get-Item $_).Length)} } | Format-Table -AutoSize
```

```powershell
# Preview batch summary
Import-Csv .\trading_activity_batch_summary.csv | Select-Object -First 10 | Format-Table -AutoSize
```

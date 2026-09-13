"""Manual ingestion of an official document already present on this PC.

    python -m app.ingestion.cli --amc hdfc  --file "data/raw/2026-07/HDFC/factsheet.pdf"
    python -m app.ingestion.cli --amc icici --file "...pdf" --portfolio "...zip"
"""
import argparse
import json
import sys
from datetime import datetime
from app.db.session import SessionLocal
from app.ingestion.pipeline import ingest_local_file, DOWNLOADERS
from app.ingestion.service import write_report


def month(value):
    return datetime.strptime(value, '%Y-%m').date().replace(day=1)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='app.ingestion.cli', description=__doc__)
    parser.add_argument('--amc', required=True, choices=sorted(DOWNLOADERS))
    parser.add_argument('--file', required=True, help='Official factsheet PDF on this PC')
    parser.add_argument('--portfolio', help='Official monthly portfolio disclosure (.xlsx/.zip)')
    parser.add_argument('--target-month', type=month, help='YYYY-MM; defaults to the month stated in the document')
    parser.add_argument('--no-gemini', action='store_true', help='Deterministic extraction only')
    parser.add_argument('--report', action='store_true', help='Also write data/reports files')
    args = parser.parse_args(argv)

    with SessionLocal() as session:
        run = ingest_local_file(session, args.amc, args.file, args.target_month,
                                args.portfolio, use_gemini=not args.no_gemini)
        summary = {'run_id': run.id, 'amc': args.amc, 'target_month': run.target_month.isoformat(),
                   'status': run.status, 'schemes_detected': run.schemes_detected,
                   'equity_schemes_detected': run.equity_schemes_detected,
                   'schemes_successful': run.schemes_successful, 'schemes_failed': run.schemes_failed,
                   'holdings_inserted': run.holdings_inserted, 'coverage': run.coverage,
                   'error_summary': run.error_summary}
        if args.report:
            write_report(session, [run])
    print(json.dumps(summary, indent=2, default=str))
    return 0 if run.status in ('SUCCESS', 'PARTIAL_SUCCESS') else 1


if __name__ == '__main__':
    sys.exit(main())

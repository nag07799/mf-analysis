"""Scheduled monthly ingestion.

Task Scheduler should fire this daily from the 10th to the 15th. An AMC/month that has
already been ingested successfully is skipped, so delayed publication is safe and repeated
runs never duplicate a snapshot.

    python -m app.ingestion.monthly_job
    python -m app.ingestion.monthly_job --target-month 2026-08
"""
import argparse
import json
import logging
import sys
from datetime import date, datetime
from sqlalchemy import select
from app.config import settings
from app.db.models import IngestionRun, AMC
from app.db.session import SessionLocal
from app.ingestion.pipeline import DOWNLOADERS, previous_month, run_amc
from app.ingestion.service import get_amc, write_report

RETRY_WINDOW = range(10, 16)
COMPLETE = ('SUCCESS', 'PARTIAL_SUCCESS')
log = logging.getLogger('monthly_job')


def configure_logging(root):
    folder = root / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s',
                        handlers=[logging.FileHandler(folder / f'{date.today():%Y-%m}_job.log', encoding='utf-8'),
                                  logging.StreamHandler(sys.stderr)])


def already_complete(session, amc_id, target_month):
    return session.scalar(select(IngestionRun).where(
        IngestionRun.amc_id == amc_id, IngestionRun.target_month == target_month,
        IngestionRun.status.in_(COMPLETE))) is not None


def main(argv=None):
    parser = argparse.ArgumentParser(prog='app.ingestion.monthly_job', description=__doc__)
    parser.add_argument('--target-month', help='YYYY-MM; defaults to the previous calendar month')
    parser.add_argument('--amc', action='append', choices=sorted(DOWNLOADERS),
                        help='Restrict the run; repeatable. Defaults to every configured AMC.')
    parser.add_argument('--force', action='store_true', help='Re-run an AMC/month already marked complete')
    parser.add_argument('--no-gemini', action='store_true')
    parser.add_argument('--ignore-window', action='store_true',
                        help='Run outside the 10th-15th retry window')
    args = parser.parse_args(argv)

    root = settings.archive_root()
    configure_logging(root)
    target_month = (datetime.strptime(args.target_month, '%Y-%m').date().replace(day=1)
                    if args.target_month else previous_month())
    today = date.today()
    if not args.target_month and not args.ignore_window and today.day not in RETRY_WINDOW:
        log.info('Outside the %s-%s retry window; nothing to do.', RETRY_WINDOW.start, RETRY_WINDOW.stop - 1)
        return 0

    slugs = args.amc or sorted(DOWNLOADERS)
    runs, skipped = [], []
    with SessionLocal() as session:
        for slug in slugs:
            amc = get_amc(session, slug)
            session.commit()
            if not args.force and already_complete(session, amc.id, target_month):
                log.info('%s %s already ingested; skipping.', slug, target_month)
                skipped.append(slug)
                continue
            log.info('Ingesting %s for %s', slug, target_month)
            try:
                run = run_amc(session, slug, target_month, root=root, use_gemini=not args.no_gemini)
            except Exception as exc:
                session.rollback()
                log.exception('%s failed', slug)
                run = IngestionRun(target_month=target_month, amc_id=amc.id, status='FAILED',
                                   error_summary=f'{type(exc).__name__}: {exc}'[:4000],
                                   completed_at=datetime.now())
                session.add(run)
                session.commit()
            log.info('%s -> %s (%s equity schemes, %s holdings)', slug, run.status,
                     run.equity_schemes_detected, run.holdings_inserted)
            runs.append(run)
        report = write_report(session, runs, root) if runs else {'runs': [], 'overall': {}}
    report['skipped_already_complete'] = skipped
    print(json.dumps(report, indent=2, default=str))
    if not runs:
        return 0
    statuses = {r.status for r in runs}
    if statuses == {'NOT_YET_AVAILABLE'}:
        # Exit code 2 lets Task Scheduler distinguish "not published yet" from a real failure.
        return 2
    return 0 if statuses <= set(COMPLETE) else 1


if __name__ == '__main__':
    sys.exit(main())

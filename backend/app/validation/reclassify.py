"""Re-apply the current scope rules to schemes already in the database.

The in-scope universe is actively managed domestic equity.  When that scope
changes - tax savers, equity ETFs, index and other passive schemes, debt,
hybrid, equity savings, fund-of-funds and solution-oriented plans are all out -
rows ingested under the older rules keep their old verdict until this runs.

    python -m app.validation.reclassify --dry-run
    python -m app.validation.reclassify --apply
"""
import argparse
import json
import sys

from sqlalchemy import select

from app.db.models import Scheme
from app.db.session import SessionLocal
from app.validation.classification import classify


class _Subject:
    """The field surface classify() reads, backed by a stored scheme.

    classify() was written for a freshly parsed scheme.  A stored row keeps the
    label it was judged on in classification_evidence, so the same decision can
    be reproduced without re-reading the source document.
    """

    def __init__(self, scheme: Scheme):
        self.category = scheme.category
        self.official_description = scheme.classification_evidence or ""
        self.asset_class = scheme.asset_class
        self.classification_status = scheme.classification_status
        self.management_style = scheme.management_style
        self.classification_evidence = scheme.classification_evidence


def reclassify(session, apply: bool):
    changes = []
    for scheme in session.scalars(select(Scheme)):
        before = (scheme.asset_class, scheme.classification_status)
        subject = classify(_Subject(scheme))
        scheme.asset_class = subject.asset_class
        scheme.classification_status = subject.classification_status
        scheme.management_style = subject.management_style
        scheme.classification_evidence = subject.classification_evidence
        after = (scheme.asset_class, scheme.classification_status)
        if before != after:
            changes.append({
                "id": scheme.id,
                "scheme": scheme.scheme_name,
                "category": scheme.category,
                "from": {"asset_class": before[0], "status": before[1]},
                "to": {"asset_class": after[0], "status": after[1]},
            })
    if apply:
        session.commit()
    else:
        session.rollback()
    return changes


def main(argv=None):
    parser = argparse.ArgumentParser(prog="app.validation.reclassify", description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Report changes only")
    group.add_argument("--apply", action="store_true", help="Write the new verdicts")
    args = parser.parse_args(argv)

    with SessionLocal() as session:
        changes = reclassify(session, apply=args.apply)
    summary = {
        "applied": args.apply,
        "changed": len(changes),
        "now_excluded": sum(1 for c in changes if c["to"]["status"] == "EXCLUDED"),
        "changes": changes,
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

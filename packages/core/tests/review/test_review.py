import uuid
from concurrent.futures import ThreadPoolExecutor
from itertools import pairwise

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from shotkeepr.core.adapters.persistence.models import ManualStatusChangeRow
from shotkeepr.core.adapters.persistence.review import SqlReviewRepository
from shotkeepr.core.adapters.review.factory import review_service
from shotkeepr.core.domain.catalog import SessionStatus
from shotkeepr.core.domain.catalog.review import ReviewError, ReviewShotNotFoundError, ReviewStatus

from ..quality.conftest import ExposureCatalog


def test_review_persists_without_originals_and_does_not_claim_analysis(
    catalog: ExposureCatalog,
) -> None:
    service = review_service(catalog.db, catalog.data)
    default = service.get(catalog.shot.shot_id)
    assert default.status is ReviewStatus.REVIEW
    assert default.updated_at is None
    catalog.shot.files[0].path.unlink()
    kept = service.set_status(catalog.shot.shot_id, ReviewStatus.KEEP)
    assert kept.updated_at is not None and kept.updated_at.tzinfo is not None
    assert service.set_status(catalog.shot.shot_id, ReviewStatus.KEEP) == kept
    restarted = review_service(catalog.db, catalog.data)
    assert restarted.get(catalog.shot.shot_id) == kept
    rejected = restarted.set_status(catalog.shot.shot_id, ReviewStatus.REJECT)
    assert rejected.status is ReviewStatus.REJECT
    assert catalog.sessions.get(catalog.session.session_id) == catalog.session
    assert catalog.results.get(catalog.shot.shot_id) is None
    with catalog.db.transaction() as tx:
        changes = tx.scalars(select(ManualStatusChangeRow).order_by(ManualStatusChangeRow.at)).all()
        assert [(row.old_status, row.new_status) for row in changes] == [
            ("REVIEW", "KEEP"),
            ("KEEP", "REJECT"),
        ]
        assert all(row.shot_id == catalog.shot.shot_id for row in changes)


def test_audit_failure_rolls_back_the_decision(catalog: ExposureCatalog) -> None:
    service = review_service(catalog.db, catalog.data)

    def fail_history(conn: object, cursor: object, statement: str, *args: object) -> None:
        if "INSERT INTO manual_status_changes" in statement:
            raise SQLAlchemyError("audit unavailable")

    event.listen(catalog.db.engine, "before_cursor_execute", fail_history)
    try:
        with pytest.raises(SQLAlchemyError, match="audit unavailable"):
            service.set_status(catalog.shot.shot_id, ReviewStatus.KEEP)
    finally:
        event.remove(catalog.db.engine, "before_cursor_execute", fail_history)
    assert SqlReviewRepository(catalog.db).get(catalog.shot.shot_id) is None
    with catalog.db.transaction() as tx:
        assert tx.scalars(select(ManualStatusChangeRow)).all() == []


def test_concurrent_updates_have_a_consistent_audit_chain(catalog: ExposureCatalog) -> None:
    service = review_service(catalog.db, catalog.data)
    statuses = [ReviewStatus.KEEP, ReviewStatus.REJECT, ReviewStatus.REVIEW] * 3
    with ThreadPoolExecutor(max_workers=3) as executor:
        list(
            executor.map(lambda status: service.set_status(catalog.shot.shot_id, status), statuses)
        )
    with catalog.db.transaction() as tx:
        rows = tx.scalars(select(ManualStatusChangeRow).order_by(ManualStatusChangeRow.at)).all()
        assert rows[0].old_status == "REVIEW"
        assert all(left.new_status == right.old_status for left, right in pairwise(rows))
        assert rows[-1].new_status == service.get(catalog.shot.shot_id).status.value


def test_unknown_and_active_shots_are_not_reviewed(catalog: ExposureCatalog) -> None:
    service = review_service(catalog.db, catalog.data)
    with pytest.raises(ReviewShotNotFoundError):
        service.set_status(uuid.uuid4(), ReviewStatus.KEEP)
    catalog.session.status = SessionStatus.ANALYZING
    catalog.sessions.update(catalog.session)
    with pytest.raises(ReviewError, match="elaborazione"):
        service.set_status(catalog.shot.shot_id, ReviewStatus.REJECT)
    assert service.reviews.get(catalog.shot.shot_id) is None


def test_export_rejects_a_stale_review_before_writing(catalog: ExposureCatalog) -> None:
    service = review_service(catalog.db, catalog.data)
    service.set_status(catalog.shot.shot_id, ReviewStatus.KEEP)
    with pytest.raises(ReviewError, match="Stato modificato"):
        service.export(catalog.shot.shot_id, ReviewStatus.REJECT)
    assert not catalog.shot.files[0].path.with_suffix(".xmp").exists()

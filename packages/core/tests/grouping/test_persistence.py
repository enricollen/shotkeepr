import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from shotkeepr.core.adapters.grouping.factory import grouping_service
from shotkeepr.core.adapters.persistence.models import (
    GroupCorrectionRow,
    GroupRow,
    SelectionRunRow,
    ShotRow,
)
from shotkeepr.core.adapters.review.factory import review_service
from shotkeepr.core.domain.catalog import Session, SessionStatus
from shotkeepr.core.domain.catalog.grouping import GroupingError, GroupingSessionNotFoundError
from shotkeepr.core.domain.catalog.review import ReviewStatus

from ..quality.conftest import ExposureCatalog
from .conftest import shot


def test_grouping_persists_and_regrouping_preserves_reviews_and_exposure(
    catalog: ExposureCatalog,
) -> None:
    shots = [shot(catalog.session.session_id, seconds) for seconds in (0, 1, 3, 20)]
    catalog.shots.add_many(shots)
    reviewed = review_service(catalog.db, catalog.data).set_status(
        shots[1].shot_id, ReviewStatus.KEEP
    )
    exposure = catalog.service.measure(catalog.shot.shot_id)
    service = grouping_service(catalog.db)
    initial = service.get(catalog.session.session_id)
    assert initial.groups == () and initial.grouped_at is None and initial.ungrouped_shots == 5
    result = service.regroup(catalog.session.session_id, 2)
    assert len(result.groups) == 1
    assert result.groups[0].shots == 3
    assert result.groups[0].first_capture == shots[0].capture_time
    assert result.groups[0].last_capture == shots[2].capture_time
    assert result.ungrouped_shots == 2
    assert result.grouped_at is not None and result.grouped_at.tzinfo is UTC
    assert grouping_service(catalog.db).get(catalog.session.session_id) == result
    assert service.regroup(catalog.session.session_id, 2) == result
    members = catalog.shots.list_by_session(
        catalog.session.session_id, group_id=result.groups[0].group_id
    )
    assert {item.shot_id for item in members} == {item.shot_id for item in shots[:3]}
    assert (
        catalog.shots.count_by_session(
            catalog.session.session_id, group_id=result.groups[0].group_id
        )
        == 3
    )
    assert catalog.shots.count_by_session(catalog.session.session_id, ungrouped=True) == 2
    assert len(catalog.shots.list_by_session(catalog.session.session_id, ungrouped=True)) == 2
    changed = service.regroup(catalog.session.session_id, 0.5)
    assert changed.groups == () and changed.ungrouped_shots == 5
    assert all(
        item.group_id is None for item in catalog.shots.list_by_session(catalog.session.session_id)
    )
    assert service.regroup(catalog.session.session_id, 2).groups == result.groups
    assert review_service(catalog.db, catalog.data).get(shots[1].shot_id) == reviewed
    assert catalog.results.get(catalog.shot.shot_id) == exposure
    assert catalog.sessions.get(catalog.session.session_id) == catalog.session


def test_failed_rebuild_leaves_the_previous_grouping_intact(
    catalog: ExposureCatalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog.shots.add_many(
        [shot(catalog.session.session_id, 0), shot(catalog.session.session_id, 1)]
    )
    service = grouping_service(catalog.db)
    saved = service.regroup(catalog.session.session_id, 2)
    before = catalog.shots.list_by_session(catalog.session.session_id)

    def fail_config(conn: object, cursor: object, statement: str, *args: object) -> None:
        if statement.startswith("UPDATE burst_grouping"):
            raise SQLAlchemyError("disk failure")

    event.listen(catalog.db.engine, "before_cursor_execute", fail_config)
    try:
        with pytest.raises(SQLAlchemyError, match="disk failure"):
            service.regroup(catalog.session.session_id, 0.5)
    finally:
        event.remove(catalog.db.engine, "before_cursor_execute", fail_config)
    assert service.get(catalog.session.session_id) == saved
    assert catalog.shots.list_by_session(catalog.session.session_id) == before


@pytest.mark.parametrize("protection", ["manual", "cluster", "correction", "selection"])
def test_other_work_is_not_silently_overwritten(catalog: ExposureCatalog, protection: str) -> None:
    with catalog.db.transaction() as tx:
        group_id = uuid.uuid4()
        if protection in {"manual", "cluster"}:
            tx.add(
                GroupRow(
                    id=group_id,
                    session_id=catalog.session.session_id,
                    kind="CLUSTER" if protection == "cluster" else "BURST",
                    is_manual=protection == "manual",
                )
            )
            tx.flush()
            tx.get(ShotRow, catalog.shot.shot_id).group_id = group_id
        elif protection == "correction":
            tx.add(
                GroupCorrectionRow(
                    id=uuid.uuid4(),
                    session_id=catalog.session.session_id,
                    type="MOVE",
                    to_group=group_id,
                    at=datetime.now(UTC),
                )
            )
        else:
            tx.add(
                SelectionRunRow(
                    id=uuid.uuid4(),
                    session_id=catalog.session.session_id,
                    settings_snapshot={},
                    created_at=datetime.now(UTC),
                )
            )
    with pytest.raises(GroupingError, match="protetto"):
        grouping_service(catalog.db).regroup(catalog.session.session_id, 2)
    if protection in {"manual", "cluster"}:
        assert catalog.shots.get(catalog.shot.shot_id).group_id == group_id


@pytest.mark.parametrize(
    "status",
    [
        SessionStatus.CREATED,
        SessionStatus.IMPORTING,
        SessionStatus.ANALYZING,
        SessionStatus.CANCELLED,
        SessionStatus.FAILED,
    ],
)
def test_incomplete_sessions_are_not_grouped(
    catalog: ExposureCatalog, status: SessionStatus
) -> None:
    catalog.session.status = status
    catalog.sessions.update(catalog.session)
    with pytest.raises(GroupingError, match="consentito"):
        grouping_service(catalog.db).regroup(catalog.session.session_id, 2)


def test_unknown_session_is_an_explicit_error(catalog: ExposureCatalog) -> None:
    service = grouping_service(catalog.db)
    with pytest.raises(GroupingSessionNotFoundError):
        service.get(uuid.uuid4())
    with pytest.raises(GroupingSessionNotFoundError):
        service.regroup(uuid.uuid4(), 2)


def test_no_decoding_or_originals_are_needed(catalog: ExposureCatalog) -> None:
    catalog.shot.files[0].path.unlink()
    catalog.preview.unlink()
    result = grouping_service(catalog.db).regroup(catalog.session.session_id, 2)
    assert result.groups == ()
    assert result.ungrouped_shots == 1


def test_concurrent_identical_regroups_are_serialized_and_idempotent(
    catalog: ExposureCatalog,
) -> None:
    catalog.shots.add_many(
        [shot(catalog.session.session_id, 0), shot(catalog.session.session_id, 1)]
    )
    service = grouping_service(catalog.db)
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(
            executor.map(lambda _: service.regroup(catalog.session.session_id, 2), range(6))
        )
    assert all(item == results[0] for item in results)
    assert len(service.get(catalog.session.session_id).groups) == 1


def test_a_new_shot_updates_group_membership_and_unchanged_metadata_is_repaired(
    catalog: ExposureCatalog,
) -> None:
    initial = [shot(catalog.session.session_id, 0), shot(catalog.session.session_id, 1)]
    catalog.shots.add_many(initial)
    service = grouping_service(catalog.db)
    before = service.regroup(catalog.session.session_id, 2)
    extra = shot(catalog.session.session_id, 2)
    catalog.shots.add_many([extra])
    result = service.regroup(catalog.session.session_id, 2)
    assert result.groups[0].shots == 3
    assert result.groups[0].group_id != before.groups[0].group_id
    with catalog.db.transaction() as tx:
        row = tx.get(GroupRow, result.groups[0].group_id)
        row.camera_model = "Incorrect persisted model"
    repaired = service.regroup(catalog.session.session_id, 2)
    assert repaired.groups == result.groups


def test_empty_imported_session_has_a_persisted_empty_result(catalog: ExposureCatalog) -> None:
    empty = Session(catalog.session.source_folder, status=SessionStatus.IMPORTED)
    catalog.sessions.add(empty)
    result = grouping_service(catalog.db).regroup(empty.session_id, 2)
    assert result.groups == () and result.ungrouped_shots == 0
    assert result.grouped_at is not None

import uuid
from dataclasses import replace
from datetime import UTC, timedelta, timezone

import pytest

from shotkeepr.core.domain.catalog.grouping import GroupingError, build_bursts

from .conftest import shot


def test_inclusive_gap_and_chaining_are_deterministic() -> None:
    session = uuid.uuid4()
    shots = [shot(session, seconds) for seconds in (0, 2, 4, 6.000001)]
    result = build_bursts(session, list(reversed(shots)), 2)
    assert len(result) == 1
    assert result[0].shot_ids == tuple(item.shot_id for item in shots[:3])
    assert result[0].group.shots == 3
    assert result[0].group.first_capture == shots[0].capture_time
    assert result[0].group.last_capture == shots[2].capture_time
    assert build_bursts(session, shots, 2) == result
    assert build_bursts(session, shots[:3], 5)[0].group.group_id == result[0].group.group_id


def test_cameras_are_grouped_independently_even_with_interleaved_times() -> None:
    session = uuid.uuid4()
    first = [shot(session, 0), shot(session, 1)]
    second = [shot(session, 0.5, serial="CAM-2"), shot(session, 1.5, serial="CAM-2")]
    different_model = [
        shot(session, 0, model="Other camera"),
        shot(session, 1, model="Other camera"),
    ]
    result = build_bursts(
        session,
        [first[0], second[0], different_model[0], first[1], second[1], different_model[1]],
        2,
    )
    assert len(result) == 3
    assert {item.group.camera_serial for item in result} == {"CAM-1", "CAM-2"}
    assert {frozenset(item.shot_ids) for item in result} == {
        frozenset(shot.shot_id for shot in group) for group in (first, second, different_model)
    }


@pytest.mark.parametrize(
    "missing", ["serial", "model", "capture", "naive", "conflict", "time-conflict", "no-files"]
)
def test_missing_or_conflicting_metadata_is_never_guessed(missing: str) -> None:
    session = uuid.uuid4()
    unknown = shot(session, 1)
    file = unknown.files[0]
    if missing == "serial":
        file.metadata = replace(file.metadata, camera_serial=None)
    elif missing == "model":
        file.metadata = replace(file.metadata, camera_model=" ")
    elif missing == "capture":
        unknown.capture_time = None
    elif missing == "naive":
        unknown.capture_time = unknown.capture_time.replace(tzinfo=None)
        file.metadata = replace(file.metadata, capture_time=unknown.capture_time)
    elif missing == "conflict":
        unknown.files.append(replace(file, metadata=replace(file.metadata, camera_serial="OTHER")))
    elif missing == "time-conflict":
        file.metadata = replace(
            file.metadata, capture_time=file.metadata.capture_time + timedelta(seconds=1)
        )
    else:
        unknown.files = []
    assert build_bursts(session, [shot(session, 0), unknown], 2) == ()


def test_utc_equivalent_offsets_do_not_split_a_burst() -> None:
    session = uuid.uuid4()
    first, second = shot(session, 0), shot(session, 1)
    second.capture_time = second.capture_time.astimezone(timezone(timedelta(hours=2)))
    result = build_bursts(session, [second, first], 2)
    assert result[0].group.last_capture.tzinfo is UTC
    assert result[0].group.shots == 2


def test_raw_jpeg_is_one_member_and_partial_metadata_can_be_combined() -> None:
    session = uuid.uuid4()
    first, second = shot(session, 0), shot(session, 1)
    raw = replace(
        first.files[0], format="NEF", metadata=replace(first.files[0].metadata, camera_serial=None)
    )
    first.files.insert(0, raw)
    result = build_bursts(session, [first, second], 2)
    assert len(result) == 1
    assert result[0].group.shots == 2


@pytest.mark.parametrize("gap", [0, -1, 60.01, float("nan"), float("inf"), True])
def test_invalid_gaps_fail_explicitly(gap: float) -> None:
    with pytest.raises(GroupingError):
        build_bursts(uuid.uuid4(), [], gap)


def test_cross_session_or_duplicate_members_are_rejected() -> None:
    session = uuid.uuid4()
    item = shot(session, 0)
    with pytest.raises(GroupingError):
        build_bursts(session, [item, item], 2)
    with pytest.raises(GroupingError):
        build_bursts(uuid.uuid4(), [item], 2)


def test_large_unsorted_session_has_one_membership_per_shot() -> None:
    session = uuid.uuid4()
    shots = [shot(session, index * 0.1, serial=f"CAM-{index % 4}") for index in range(10000)]
    groups = build_bursts(session, list(reversed(shots)), 2)
    assert len(groups) == 4
    assigned = [member for group in groups for member in group.shot_ids]
    assert len(assigned) == len(set(assigned)) == 10000

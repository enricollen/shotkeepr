"""Temporal bursts, independent of visual similarity and photographic quality."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from shotkeepr.core.domain.catalog.model import Shot

BURST_METHOD = "camera-time-bursts-v1"
DEFAULT_GAP_SECONDS = 2.0
MIN_GAP_SECONDS = 0.01
MAX_GAP_SECONDS = 60.0


class GroupingError(RuntimeError):
    """A grouping cannot be published without losing catalog integrity."""


class GroupingSessionNotFoundError(GroupingError):
    """The requested session is absent from the catalog."""


@dataclass(frozen=True, slots=True)
class BurstGroup:
    group_id: uuid.UUID
    camera_model: str
    camera_serial: str
    shots: int
    first_capture: datetime
    last_capture: datetime


@dataclass(frozen=True, slots=True)
class PlannedBurst:
    group: BurstGroup
    shot_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class BurstGrouping:
    session_id: uuid.UUID
    gap_seconds: float | None
    method_version: str | None
    grouped_at: datetime | None
    groups: tuple[BurstGroup, ...]
    ungrouped_shots: int


def validate_gap(gap_seconds: float) -> None:
    if (
        isinstance(gap_seconds, bool)
        or not math.isfinite(gap_seconds)
        or not MIN_GAP_SECONDS <= gap_seconds <= MAX_GAP_SECONDS
    ):
        raise GroupingError(
            f"Intervallo raffica deve essere finito e compreso tra {MIN_GAP_SECONDS} e "
            f"{MAX_GAP_SECONDS} secondi"
        )


def _camera(shot: Shot) -> tuple[str, str] | None:
    models = {
        file.metadata.camera_model.strip()
        for file in shot.files
        if file.metadata.camera_model and file.metadata.camera_model.strip()
    }
    serials = {
        file.metadata.camera_serial.strip()
        for file in shot.files
        if file.metadata.camera_serial and file.metadata.camera_serial.strip()
    }
    if len(models) != 1 or len(serials) != 1:
        return None
    if any(
        file.metadata.capture_time is not None and file.metadata.capture_time != shot.capture_time
        for file in shot.files
    ):
        return None
    return next(iter(models)), next(iter(serials))


def _captured(shot: Shot) -> datetime | None:
    value = shot.capture_time
    if value is None or value.utcoffset() is None:
        return None
    return value.astimezone(UTC)


def grouping_fingerprint(shots: Sequence[Shot]) -> str:
    inputs = [
        (
            str(shot.shot_id),
            shot.capture_time.isoformat() if shot.capture_time is not None else None,
            _camera(shot),
        )
        for shot in sorted(shots, key=lambda item: item.shot_id.int)
    ]
    return hashlib.sha256(json.dumps(inputs, ensure_ascii=True).encode("ascii")).hexdigest()


def _planned(
    session_id: uuid.UUID, camera: tuple[str, str], members: Sequence[tuple[datetime, Shot]]
) -> PlannedBurst:
    ids = tuple(shot.shot_id for _, shot in members)
    group_id = uuid.uuid5(
        session_id, BURST_METHOD + ":" + ",".join(str(item) for item in sorted(ids))
    )
    return PlannedBurst(
        BurstGroup(group_id, *camera, len(members), members[0][0], members[-1][0]), ids
    )


def build_bursts(
    session_id: uuid.UUID, shots: Sequence[Shot], gap_seconds: float
) -> tuple[PlannedBurst, ...]:
    validate_gap(gap_seconds)
    if len({shot.shot_id for shot in shots}) != len(shots) or any(
        shot.session_id != session_id for shot in shots
    ):
        raise GroupingError("Scatti duplicati o appartenenti a una sessione diversa")
    cameras: dict[tuple[str, str], list[tuple[datetime, Shot]]] = defaultdict(list)
    for shot in shots:
        camera, captured = _camera(shot), _captured(shot)
        if camera is not None and captured is not None:
            cameras[camera].append((captured, shot))
    groups: list[PlannedBurst] = []
    gap = timedelta(seconds=gap_seconds)
    for camera, candidates in sorted(cameras.items()):
        ordered = sorted(candidates, key=lambda item: (item[0], item[1].shot_id.int))
        members: list[tuple[datetime, Shot]] = []
        for item in ordered:
            if members and item[0] - members[-1][0] > gap:
                if len(members) > 1:
                    groups.append(_planned(session_id, camera, members))
                members = []
            members.append(item)
        if len(members) > 1:
            groups.append(_planned(session_id, camera, members))
    return tuple(
        sorted(groups, key=lambda item: (item.group.first_capture, item.group.group_id.int))
    )

from shotkeepr.core.adapters.persistence.db import Database
from shotkeepr.core.adapters.persistence.grouping import SqlGroupingRepository
from shotkeepr.core.application.grouping import GroupingService


def grouping_service(db: Database) -> GroupingService:
    return GroupingService(SqlGroupingRepository(db))

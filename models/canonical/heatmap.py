from typing import List, Optional

from pydantic import BaseModel, Field


class HeatDay(BaseModel):
    date: str
    count: int
    level: int


class YearContribution(BaseModel):
    year: int
    totalSubmissions: int
    activeDays: int


class Heatmap(BaseModel):
    totalSubmissions: int = 0
    totalActiveDays: int = 0
    currentStreak: int = 0
    longestStreak: int = 0
    maxDailySubmissions: int = 0
    firstActiveDate: Optional[str] = None
    lastActiveDate: Optional[str] = None
    dailyContributions: List[HeatDay] = Field(default_factory=list)
    yearlyContributions: List[YearContribution] = Field(default_factory=list)
    availableYears: List[int] = Field(default_factory=list)
    view: str = "all"  # all | last_365 | year
    year: Optional[int] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    # GitHost additions (additive to the canonical schema):
    # where this calendar came from and whether the deep walk finished.
    #   native      -> instance /users/{u}/heatmap, capped at ~371 days
    #   synthesized -> rebuilt from per-repo commit walks, full history
    source: str = "native"
    complete: bool = True

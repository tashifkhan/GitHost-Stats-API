from typing import Optional

from pydantic import BaseModel


class Summary(BaseModel):
    totalSolved: int = 0
    totalActiveDays: int = 0
    # GitHost additions (additive to the canonical schema)
    totalRepos: Optional[int] = None
    totalStars: Optional[int] = None
    totalForks: Optional[int] = None
    followers: Optional[int] = None


class RepoSummary(BaseModel):
    id: int
    name: str
    fullName: Optional[str] = None
    description: Optional[str] = None
    htmlUrl: Optional[str] = None
    stars: int = 0
    forks: int = 0
    watchers: int = 0
    openIssues: int = 0
    language: Optional[str] = None
    isFork: bool = False
    isMirror: bool = False
    isPrivate: bool = False
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    pushedAt: Optional[str] = None


class Repos(BaseModel):
    count: int = 0
    totalStars: int = 0
    totalForks: int = 0
    repos: list[RepoSummary] = []


class Orgs(BaseModel):
    count: int = 0
    orgs: list[dict] = []
    # True when the instance refuses to list orgs without a token
    # (Forgejo does this for anonymous callers on some configurations).
    restricted: bool = False

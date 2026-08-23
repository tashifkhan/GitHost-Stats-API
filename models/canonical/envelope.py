from typing import Any, Dict, Optional

from pydantic import BaseModel


def make_envelope(
    username: str,
    data: Any,
    *,
    family: str = "gitea",
    instance: Optional[str] = None,
    software: Optional[Dict[str, str]] = None,
    cached: bool = False,
    status: str = "success",
    message: str = "retrieved",
) -> Dict[str, Any]:
    """Canonical envelope with GitHost's additive fields.

    ``family`` is the software dialect that answered ("forgejo" or "gitea"),
    ``instance`` the registry key (or hostname for caller-supplied base URLs),
    and ``software`` a {"name", "version"} block from the version probe.
    """
    if isinstance(data, BaseModel):
        data = data.model_dump()
    envelope: Dict[str, Any] = {
        "status": status,
        "message": message,
        "platform": family,
        "username": username,
        "cached": cached,
        "data": data,
    }
    if instance is not None:
        envelope["instance"] = instance
    if software is not None:
        envelope["software"] = software
    return envelope

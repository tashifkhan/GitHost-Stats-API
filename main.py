from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import settings
from core.middleware import CacheRateLimitMiddleware
from services.client import UpstreamError
from services.registry import parse_instances


app = FastAPI(
    title="GitHost Stats API",
    description=(
        "One stats API for every git host: Forgejo, Gitea, Codeberg, or any "
        "instance by base URL. Canonical sections per user: summary, profile, "
        "stats, heatmap (view=all|last_365|year), badges, plus repos and orgs. "
        "Pick a target with ?host=<key>, ?base_url=https://..., or the "
        "embed-safe /f/{host}/{username}/... prefix. deep=true rebuilds full "
        "history from commit walks."
    ),
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(CacheRateLimitMiddleware, platform="githost")


@app.exception_handler(UpstreamError)
async def upstream_error_handler(request: Request, exc: UpstreamError):
    if exc.status_code == 404:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "User does not exist"},
        )
    return JSONResponse(
        status_code=502,
        content={
            "status": "error",
            "message": f"Upstream host error: {exc.message}",
        },
    )


# System routes register BEFORE the catch-all /{username} route.
@app.get("/healthz", include_in_schema=False)
async def healthz():
    from core.cache import redis_enabled

    targets = parse_instances()
    return {
        "status": "ok",
        "redis": redis_enabled(),
        "instances": [
            {"key": t.key, "baseUrl": t.base_url, "token": bool(t.token)} for t in targets.values()
        ],
    }


from routes.docs import router as docs_router

app.include_router(docs_router)

from routes.canonical import router as canonical_router

app.include_router(canonical_router)


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(
        "main:app",
        reload=True,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8008")),
    )

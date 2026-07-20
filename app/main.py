"""MEMIND FastAPI application entry point."""

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Import routes
from app.routes import auth, memories, stories, wiki
from app.jobs.scheduler import scheduler
from app.db import Base, engine
from app.agents.capture import _ollama_config

import httpx

tags_metadata = [
    {
        "name": "health",
        "description": "Health check endpoints",
    },
    {
        "name": "auth",
        "description": "User authentication (login, register, token refresh)",
    },
    {
        "name": "memories",
        "description": "Memory capture, retrieval, editing, deletion",
    },
    {
        "name": "search",
        "description": "Hybrid search (full-text, semantic, filters)",
    },
    {
        "name": "stories",
        "description": "Story generation and retrieval",
    },
    {
        "name": "timeline",
        "description": "Timeline view of memories",
    },
    {
        "name": "insights",
        "description": "User insights and statistics",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events (startup/shutdown)."""
    # Startup
    print("MEMIND application starting...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database tables ensured.")
    scheduler.start()
    print("APScheduler started.")
    yield
    # Shutdown
    scheduler.shutdown(wait=False)
    print("APScheduler shut down.")
    print("MEMIND application shutting down...")


# Create FastAPI app
app = FastAPI(
    title="MEMIND API",
    description="AI-powered memory capture and enhancement platform",
    version="0.1.0",
    openapi_tags=tags_metadata,
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8000",
    ],  # Add frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/health", tags=["health"])
async def health_check():
    """Check if API is running."""
    return {"status": "healthy", "version": "0.1.0"}


@app.get("/health/ollama", tags=["health"])
async def ollama_health_check():
    """Check if the configured Ollama API is reachable."""
    api_base, model, api_key = _ollama_config()
    url = f"{api_base}/models" if api_base.endswith("/v1") else f"{api_base}/v1/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            models = [m.get("id", m.get("model")) for m in data.get("data", [])]
            return {
                "reachable": True,
                "base_url": api_base,
                "configured_model": model,
                "available_models": models[:10],
            }
    except Exception as exc:
        return {
            "reachable": False,
            "base_url": api_base,
            "configured_model": model,
            "error": str(exc),
        }


# Include routes
app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(memories.router, prefix="/api", tags=["memories"])
app.include_router(stories.router, prefix="/api", tags=["stories"])
app.include_router(wiki.router, prefix="/api", tags=["wiki"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )

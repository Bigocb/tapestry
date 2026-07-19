"""MEMIND FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Import routes
from app.routes import auth, memories, wiki

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
    yield
    # Shutdown
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


# Include routes
app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(memories.router, prefix="/api", tags=["memories"])
app.include_router(wiki.router, prefix="/api", tags=["wiki"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )

"""FastAPI application entry point."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from wrapper.api import router
from wrapper.config import settings

# Fix for Windows: Use ProactorEventLoop for subprocess support
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    logger.info("Starting Claude Code wrapper service...")
    logger.info(f"Working directory: {settings.claude_working_dir}")

    yield

    logger.info("Shutting down Claude Code wrapper service...")


app = FastAPI(
    title="Claude Code Wrapper",
    description="REST API wrapper for Claude Code CLI orchestration",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routes
app.include_router(router, prefix="/api/v1")


# Root redirect to docs
@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint redirecting to API documentation."""
    return {"message": "Claude Code Wrapper API", "docs": "/docs"}


def main() -> None:
    """Run the application."""
    uvicorn.run(
        "wrapper.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()

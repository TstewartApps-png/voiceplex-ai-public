"""
FastAPI application entry point.

FastAPI 0.109+ as the async REST API framework.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.database import connect_to_mongodb, close_mongodb_connection, get_database
from app.utils.logging import setup_logging, set_correlation_id
from app.api.v1.router import router as api_v1_router
from app.services.voice.call_orchestrator import (
    initialize_orchestrator,
    shutdown_orchestrator,
)

# Configure logging
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting VoicePlex AI Backend...")
    await connect_to_mongodb()

    # Initialize voice call orchestrator
    db = get_database()
    await initialize_orchestrator(db)
    logger.info("Voice call orchestrator initialized")

    logger.info("VoicePlex AI Backend started successfully")

    yield

    # Shutdown
    logger.info("Shutting down VoicePlex AI Backend...")

    # Shutdown voice call orchestrator
    await shutdown_orchestrator()
    logger.info("Voice call orchestrator shut down")

    await close_mongodb_connection()
    logger.info("VoicePlex AI Backend shut down complete")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance
    """
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description="Voice Agent SaaS Platform - AI-powered voice agents for businesses",
        version="0.1.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routers
    app.include_router(api_v1_router)

    # Register exception handlers
    register_exception_handlers(app)

    # Register middleware
    register_middleware(app)

    return app


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register custom exception handlers.

    Consistent HTTP error response format: {"detail": string, "code": string}
    """

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Handle HTTP exceptions with consistent format."""
        # If detail is already a dict with our format, use it
        if isinstance(exc.detail, dict) and "detail" in exc.detail:
            return JSONResponse(
                status_code=exc.status_code,
                content=exc.detail,
            )

        # Otherwise, wrap in our format
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": str(exc.detail),
                "code": f"HTTP_{exc.status_code}",
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Handle validation errors with consistent format."""
        errors = exc.errors()

        # Format validation errors
        error_messages = []
        for error in errors:
            field = ".".join(str(loc) for loc in error["loc"])
            message = error["msg"]
            error_messages.append(f"{field}: {message}")

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": "Validation error",
                "code": "VALIDATION_ERROR",
                "errors": error_messages,
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """Handle unexpected exceptions."""
        logger.exception(f"Unexpected error: {exc}")

        settings = get_settings()

        # Don't expose internal errors in production
        if settings.is_production:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "detail": "An unexpected error occurred",
                    "code": "INTERNAL_ERROR",
                },
            )

        # In development, include error details
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": str(exc),
                "code": "INTERNAL_ERROR",
                "type": type(exc).__name__,
            },
        )


def register_middleware(app: FastAPI) -> None:
    """Register custom middleware."""

    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        """Add correlation ID to all requests for tracing."""
        # Get or generate correlation ID
        correlation_id = request.headers.get("X-Correlation-ID")
        if not correlation_id:
            from app.utils.security import generate_correlation_id
            correlation_id = generate_correlation_id()

        # Set in context for logging
        set_correlation_id(correlation_id)

        # Process request
        response = await call_next(request)

        # Add to response headers
        response.headers["X-Correlation-ID"] = correlation_id

        return response

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        """Log request details."""
        import time

        start_time = time.time()

        # Log request
        logger.info(f"Request: {request.method} {request.url.path}")

        # Process request
        response = await call_next(request)

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log response
        logger.info(
            f"Response: {request.method} {request.url.path} "
            f"status={response.status_code} duration={duration_ms:.2f}ms"
        )

        return response


# Create application instance
app = create_app()


# Health check endpoint
@app.get(
    "/health",
    tags=["Health"],
    summary="Health check",
    description="Check if the API is running and healthy.",
)
async def health_check() -> dict:
    """
    Health check endpoint.

    Returns basic service status.
    """
    return {
        "status": "healthy",
        "service": "voiceplex-api",
        "version": "0.1.0",
    }


@app.get(
    "/",
    tags=["Root"],
    summary="API root",
    description="Welcome endpoint with API information.",
)
async def root() -> dict:
    """
    Root endpoint.

    Returns basic API information.
    """
    settings = get_settings()

    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "description": "Voice Agent SaaS Platform API",
        "docs": "/docs" if settings.debug else None,
    }

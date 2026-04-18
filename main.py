"""
Entry point for Refined Chatbot API
"""
import asyncpg
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from configs.config import settings
from api.routes.chat import router as chat_router
from api.routes.health import router as health_router
from integrations.llms.vllm import create_llm
from middleware.error_handler import register_error_handlers
from middleware.logging import RequestLoggingMiddleware
from utils.logger import setup_logging
from services.observability import langfuse_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB pool and LLM instances
    langfuse_client.init()
    app.state.db_pool = await asyncpg.create_pool(settings.DATABASE_URL)
    # Backward compatibility for existing dependencies using app.state.pool
    app.state.pool = app.state.db_pool
    app.state.llm = create_llm(profile="primary")
    app.state.classifier_llm = create_llm(profile="classifier")
    app.state.summarizer_llm = create_llm(profile="summarizer")
    
    yield
    
    # Shutdown: Close DB pool
    await app.state.db_pool.close()
    langfuse_client.flush()


def create_app() -> FastAPI:
    setup_logging(debug=settings.DEBUG)

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        debug=settings.DEBUG,
        lifespan=lifespan,
    )

    # Error handlers
    register_error_handlers(app)

    # Logging
    app.add_middleware(RequestLoggingMiddleware)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(health_router, prefix="/health", tags=["Health"])
    app.include_router(chat_router, prefix="/api/v1", tags=["Chat"])

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )


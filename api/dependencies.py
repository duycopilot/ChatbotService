"""
Purpose: dependencies for Chat API and Health Check API
"""
import asyncpg
from fastapi import Request
from langchain_openai import ChatOpenAI


async def get_db(request: Request) -> asyncpg.Connection:
    pool = getattr(request.app.state, "db_pool", None) or request.app.state.pool
    async with pool.acquire() as conn:
        yield conn


def get_llm(request: Request) -> ChatOpenAI:
    return request.app.state.llm


def get_classifier_llm(request: Request) -> ChatOpenAI:
    return request.app.state.classifier_llm


def get_summarizer_llm(request: Request) -> ChatOpenAI:
    return request.app.state.summarizer_llm

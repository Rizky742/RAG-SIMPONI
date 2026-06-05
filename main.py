from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.database import engine, init_db
from app.routers import chat, schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize DB connection pool & load schema metadata
    await init_db()
    yield
    # Shutdown: close DB connections
    await engine.dispose()


app = FastAPI(
    title="Text-to-SQL Chatbot API",
    description="RAG Chatbot using Text-to-SQL with PostgreSQL, TikTok Shop & Shopee data",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api/v1", tags=["Chat"])
app.include_router(schema.router, prefix="/api/v1", tags=["Schema"])


@app.get("/")
async def root():
    return {
        "message": "Text-to-SQL Chatbot API is running",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}

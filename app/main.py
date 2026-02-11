from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from contextlib import asynccontextmanager
import json
import logging
from typing import Dict

from app.models import ChatRequest, ChatResponse, CodeGenRequest
from app.rag_engine import rag_engine

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("emmc-rag-api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    On startup, load the heavy models (RAGManager).
    """
    logger.info("Startup: Initializing RAG Engine...")
    try:
        rag_engine.initialize()
        logger.info("Startup complete: Models loaded.")
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        # In production, we might want to shut down, but here we log it.
    yield
    # Shutdown logic if any (e.g., closing DB connections)
    logger.info("Shutdown: Releasing resources...")

app = FastAPI(
    title="eMMC RAG Agent API",
    version="1.0",
    description="API for querying eMMC protocol documents and generating test cases.",
    lifespan=lifespan
)

# CORS Middleware (Crucial for frontend access)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "emmc-rag-agent"}

@app.post("/chat_stream")
async def chat_stream(request: ChatRequest):
    """
    Stream the chat response via Server-Sent Events (SSE).
    """
    async def event_generator():
        try:
            # Call the synchronous generator from rag_engine
            # Note: In a real async app, run_in_executor might be needed for heavy CPU tasks
            # to avoid blocking the event loop. Given the scale, direct call is acceptable.
            for event in rag_engine.chat_stream(request.query):
                # Format as SSE data
                yield f"data: {json.dumps(event)}\n\n"
            yield "event: end\ndata: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Error in chat stream: {e}")
            yield f"event: error\ndata: {str(e)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/generate_code", response_model=Dict[str, str])
async def generate_code_endpoint(request: CodeGenRequest):
    """
    Directly generate Python code for a known test case requirement.
    """
    try:
        code = rag_engine.generate_code_direct(request.dict())
        return {"code": code}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    # Use standard port 8000
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

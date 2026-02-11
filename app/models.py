from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class SourceItem(BaseModel):
    """
    Represents a single source chunk used in RAG
    """
    page_num: int = Field(..., description="Page number of the source document")
    content_type: str = Field(..., description="Type of content: text, table, or image")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata like caption")
    chunk_id: int = Field(..., description="Unique ID of the chunk")
    score: Optional[float] = Field(None, description="Relevance score/distance")

class ChatRequest(BaseModel):
    """
    Request model for the /chat endpoint
    """
    query: str = Field(..., description="User's question about eMMC protocol")
    top_k: int = Field(5, description="Number of context chunks to retrieve")
    stream: bool = Field(False, description="Whether to stream the response (Server-Sent Events)")

class ChatResponse(BaseModel):
    """
    Response model for the /chat endpoint (non-streaming)
    """
    answer: str = Field(..., description="LLM's answer")
    sources: List[SourceItem] = Field(default_factory=list, description="List of source chunks used")
    generated_code: Optional[str] = Field(None, description="Generated Python test case code, if applicable")
    test_case_args: Optional[Dict[str, Any]] = Field(None, description="Arguments used for test case generation")

class CodeGenRequest(BaseModel):
    """
    Request model for generating code directly (if args are known)
    """
    test_name: str
    requirements: str
    cmd_details: str

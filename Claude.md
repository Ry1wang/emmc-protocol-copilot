# Project
eMMC Protocol Intelligent Question Answering Agent.

## Structure
```
eMMC Protocol(PDF)
        ↓
    Document Parsing & Slicing
        ↓
    Embedding & Store (RAG Core)
        ↓
    Search Enhancement Generation (LLM Response)
        ↓
    Agent Orchestration (tool calls, multi-turn dialogues)
        ↓
    Front-end interface
```

## Technology selection
Development Framework: LangChain v0.3
Agent Orchestration: LangGraph
Document Parsing: PyMuPDF + PDFPlumber
Vector Database: Chroma (Development) -> Pinecone (Production)
Embedding Model: BGE-M3
LLM: DeepSeek
Frontend Interface: Chainlit
Performance Evaluation: RAGAS
Development Tools: LangSmith
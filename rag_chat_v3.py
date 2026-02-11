"""
RAG Chat (Version 3.0 - With Cross-Encoder Reranking)

Modular RAG architecture for querying eMMC protocol and generating test cases.

Architecture:
    User Query → RAGManager → Hybrid Search (Semantic + Keyword)
                            ↓
                        Reranker (Cross-Encoder)
                            ↓
                        LLMClient (DeepSeek)
                            ↓
                        Response / Generated Code

Key Improvements in v3.0:
- Added Cross-Encoder reranking for improved retrieval precision
- Expanded initial retrieval to Top-20, then rerank to Top-5
- Enhanced logging for reranking scores
"""

import json
import os
import sys
from typing import List, Dict, Optional, Any, Tuple
from dotenv import load_dotenv
from openai import OpenAI
from sentence_transformers import CrossEncoder

# Import vector DB components
try:
    from build_vector_db import EmbeddingGenerator, VectorDBManager, QueryResult
except ImportError:
    print("Warning: Could not import build_vector_db. Please ensure it is in the same directory.")
    sys.exit(1)

# Load environment variables
load_dotenv()

# ==========================================
# 1. LLM Client
# ==========================================

class LLMClient:
    """
    Handles interactions with the LLM (DeepSeek)
    """
    
    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://api.deepseek.com"):
        self.client = OpenAI(
            api_key=api_key or os.getenv("DEEPSEEK_API_KEY"),
            base_url=base_url
        )
        self.model = "deepseek-chat"
    
    def chat_completion(
        self, 
        messages: List[Dict], 
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        stream: bool = False
    ) -> Any:
        """
        Send a chat completion request
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice if tools else None,
                stream=stream
            )
            return response
        except Exception as e:
            print(f"Error calling LLM: {e}")
            return None

# ==========================================
# 2. RAG Manager with Reranking
# ==========================================

class RAGManager:
    """
    Coordinators Retrieval, Reranking, and Generation
    """
    
    def __init__(
        self, 
        db_path: str = "./vector_db", 
        collection_name: str = "emmc_chunks"
    ):
        # Initialize components
        print("Initializing RAG Manager v3.0...")
        self.embedding_generator = EmbeddingGenerator()
        self.db_manager = VectorDBManager(db_path, collection_name)
        self.llm_client = LLMClient()
        
        # Load Cross-Encoder for reranking
        print("Loading Cross-Encoder for reranking...")
        self.reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
        print("Reranker loaded successfully.")
        
        # Define tools for Function Calling
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "generate_test_case",
                    "description": "Generate a Python test case based on eMMC protocol requirements.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "test_name": {
                                "type": "string", 
                                "description": "Name of the test case, e.g. test_switch_partition"
                            },
                            "requirements": {
                                "type": "string", 
                                "description": "Technical requirements extracted from RAG context"
                            },
                            "cmd_details": {
                                "type": "string", 
                                "description": "Specific command details (index, argument format)"
                            }
                        },
                        "required": ["test_name", "requirements", "cmd_details"]
                    }
                }
            }
        ]
        
    def retrieve_context(self, query: str, top_k: int = 8) -> str:
        """
        Retrieve relevant context using Hybrid Search + Reranking
        
        Pipeline:
        1. Semantic Search (召回 Top-20)
        2. Keyword Filtering (针对 CMD 指令)
        3. Cross-Encoder Reranking (精排到 Top-5)
        """
        print(f"\n[Retrieval] Searching for: {query}")
        query_embedding = self.embedding_generator.generate_query_embedding(query)
        
        # Step 1: Initial Retrieval (召回更多候选)
        initial_k = top_k * 4  # 召回 4 倍数量用于 Rerank
        print(f"[Retrieval] Initial retrieval: Top-{initial_k}")
        
        results = self.db_manager.query(query_embedding, n_results=initial_k)
        
        # Step 2: Keyword Search (Hybrid Search)
        import re
        cmd_match = re.search(r"(CMD\d+)", query, re.IGNORECASE)
        
        if cmd_match:
            cmd_keyword = cmd_match.group(1).upper()
            print(f"[Hybrid] Keyword detected: {cmd_keyword}. Performing filtered search...")
            
            try:
                keyword_results = self.db_manager.collection.query(
                    query_embeddings=[query_embedding],
                    n_results=initial_k,
                    where_document={"$contains": cmd_keyword}
                )
                
                # Convert to QueryResult objects
                kw_res_objects = []
                if keyword_results["ids"]:
                    for i in range(len(keyword_results["ids"][0])):
                        metadata = keyword_results["metadatas"][0][i] if keyword_results["metadatas"] else {}
                        kw_res_objects.append(QueryResult(
                            chunk_id=keyword_results["ids"][0][i],
                            distance=keyword_results["distances"][0][i] if keyword_results["distances"] else 0.0,
                            content=keyword_results["documents"][0][i],
                            metadata=metadata,
                            page_num=metadata.get("page_num", 0),
                            content_type=metadata.get("content_type", "text")
                        ))
                
                # Merge results (deduplicate by chunk_id)
                existing_ids = {res.chunk_id for res in results}
                for res in kw_res_objects:
                    if res.chunk_id not in existing_ids:
                        results.append(res)
                        print(f"[Hybrid] Added keyword result: Page {res.page_num}")
                        
            except Exception as e:
                print(f"[Hybrid] Keyword search failed: {e}")
        
        # Step 3: Reranking (Cross-Encoder)
        if len(results) > top_k:
            print(f"[Rerank] Reranking {len(results)} candidates to Top-{top_k}...")
            
            # Prepare (query, document) pairs
            pairs = [(query, res.content) for res in results]
            
            # Compute relevance scores
            scores = self.reranker.predict(pairs)
            
            # Sort by score (descending)
            ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
            
            # Take Top-K
            results = [results[i] for i in ranked_indices[:top_k]]
            
            # Log reranking results
            print(f"[Rerank] Complete. Top-{top_k} scores:")
            for i, idx in enumerate(ranked_indices[:top_k], 1):
                print(f"  [{i}] Page {results[i-1].page_num} | Score: {scores[idx]:.4f}")
        
        # Build context string
        context_parts = []
        for i, res in enumerate(results, 1):
            metadata_str = f"[Source: Page {res.page_num} ({res.content_type})]"
            if res.metadata.get('caption'):
                metadata_str += f" [Caption: {res.metadata['caption']}]"
                
            context_parts.append(f"{metadata_str}\n{res.content}")
            print(f"  Result {i}: Page {res.page_num} ({res.content_type})")
            
        return "\n\n".join(context_parts)
    
    def generate_code(self, args: Dict) -> str:
        """
        Stage 2: Generate Python code based on extracted requirements
        """
        code_prompt = f"""
        Write a Python function for {args['test_name']}.

        Requirements:
        {args['requirements']}

        Command Details:
        {args['cmd_details']}

        Use `send_cmd(index, arg)` and `expect_response(expected)` as mock functions.
        Add comments explaining the bit arguments.

        IMPORTANT: 
        - Return ONLY the raw Python code. 
        - Do NOT use markdown code blocks (```python ... ```). 
        - Start directly with imports or def.
        """
        
        # Use streaming for code generation user experience
        print(f"\n[Generating Code for {args['test_name']}...]\n")
        stream = self.llm_client.chat_completion(
            messages=[{"role": "user", "content": code_prompt}],
            stream=True
        )
        
        full_code = ""
        for chunk in stream:
            if chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                print(content, end="", flush=True)
                full_code += content
        print()  # Newline after stream
        
        # Cleanup code
        full_code = full_code.replace("```python", "").replace("```", "").strip()
        return full_code
    
    def process_query_stream(self, query: str):
        """
        Main RAG Pipeline with Streaming
        """
        # 1. Retrieve with Reranking
        context = self.retrieve_context(query)
        if not context:
            yield ("text", "No relevant context found.")
            return
            
        # 2. Stage 1: Analysis & Function Calling
        messages = [
            {"role": "system", "content": """You are an eMMC protocol expert. Follow these rules strictly:

1. **For Information Queries**: If the user asks about protocol details, parameters, specifications, or "what/how/why" questions, answer directly using the provided context. DO NOT call any tools.

2. **For Code Generation Requests**: ONLY call the generate_test_case tool when the user explicitly requests to:
   - "Generate code"
   - "Write a test case"
   - "Create a function"
   - "Implement a test"
   
3. **Unknown Information**: If the answer is not in the context, say "I cannot find this information in the eMMC protocol documentation."

4. **No Hallucination**: Never make up information. Always cite the source page numbers."""},
            {"role": "user", "content": f"Context:\n{context}\n\nTask: {query}"}
        ]
        
        # First call without streaming to check for tools
        response = self.llm_client.chat_completion(messages, tools=self.tools, stream=False)
        
        if not response:
            yield ("text", "Error getting response from LLM.")
            return
            
        message = response.choices[0].message
        
        # 3. Handle Tool Calls
        if message.tool_calls:
            for tool_call in message.tool_calls:
                if tool_call.function.name == "generate_test_case":
                    args = json.loads(tool_call.function.arguments)
                    yield ("tool_start", args)
                    
                    # 4. Stage 2: Code Generation (Streamed inside generate_code)
                    code = self.generate_code(args)
                    yield ("code_result", (args['test_name'], code))
        else:
            # If no tool call, stream the text response word by word
            # Re-call with streaming enabled
            stream_response = self.llm_client.chat_completion(messages, stream=True)
            
            if stream_response:
                for chunk in stream_response:
                    if chunk.choices[0].delta.content:
                        # Yield each chunk of text as it arrives
                        yield ("text_chunk", chunk.choices[0].delta.content)


# ==========================================
# 3. CLI Interface
# ==========================================

def main():
    rag = RAGManager()
    output_dir = "./test_cases"
    os.makedirs(output_dir, exist_ok=True)
    
    print("\n" + "="*60)
    print("eMMC RAG Agent (v3.0 - With Reranking)")
    print("Type 'exit' to quit.")
    print("="*60 + "\n")
    
    while True:
        query = input("\nQuery: ").strip()
        if query.lower() in ['exit', 'quit']:
            break
        
        if not query:
            continue
            
        for event_type, data in rag.process_query_stream(query):
            if event_type == "text":
                print(f"\n[Answer]\n{data}")
            elif event_type == "tool_start":
                print(f"Target identified: {data['test_name']}")
                print(f"Requirements: {data['requirements'][:100]}...")
            elif event_type == "code_result":
                test_name, code = data
                # Save to file
                filepath = os.path.join(output_dir, f"{test_name}.py")
                with open(filepath, "w") as f:
                    f.write(code)
                print(f"\nSaved to: {filepath}")

if __name__ == "__main__":
    main()

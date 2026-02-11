"""
Vector Database Builder (Version 2.0)

Modular architecture for building and querying ChromaDB vector database
from processed PDF chunks.

Architecture:
    JSON Data → EmbeddingGenerator → VectorDBManager → Query Interface
"""

import json
import os
from typing import List, Dict, Optional, Any
from pathlib import Path

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from pydantic import BaseModel, Field


# ==========================================
# 1. Data Models
# ==========================================

class ChunkData(BaseModel):
    """
    Data model for a single chunk from clean_data.json
    """
    chunk_id: int
    page_num: int
    content: str
    content_type: str = Field(..., description="text | table | image")
    caption: str = Field(default="")
    image_path: Optional[str] = None
    metadata: Dict = Field(default_factory=dict)


class QueryResult(BaseModel):
    """
    Data model for query results
    """
    chunk_id: str
    content: str
    distance: float
    metadata: Dict
    page_num: int
    content_type: str


# ==========================================
# 2. Embedding Generator
# ==========================================

class EmbeddingGenerator:
    """
    Handles text-to-vector conversion using SentenceTransformer
    
    Responsibilities:
        - Load embedding model
        - Generate embeddings for documents
        - Generate embeddings for queries
        - Cache model for reuse
    """
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize embedding model
        
        Args:
            model_name: HuggingFace model name for embeddings
        """
        self.model_name = model_name
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """Load the SentenceTransformer model"""
        print(f"Loading embedding model: {self.model_name}...")
        self.model = SentenceTransformer(self.model_name)
        print(f"Model loaded. Embedding dimension: {self.model.get_sentence_embedding_dimension()}")
    
    def generate_embeddings(self, texts: List[str], show_progress: bool = True) -> List[List[float]]:
        """
        Generate embeddings for a list of texts
        
        Args:
            texts: List of text strings to embed
            show_progress: Whether to show progress bar
            
        Returns:
            List of embedding vectors
        """
        print(f"Generating embeddings for {len(texts)} documents...")
        embeddings = self.model.encode(
            texts,
            show_progress_bar=show_progress,
            convert_to_numpy=True
        )
        return embeddings.tolist()
    
    def generate_query_embedding(self, query: str) -> List[float]:
        """
        Generate embedding for a single query
        
        Args:
            query: Query text
            
        Returns:
            Embedding vector
        """
        embedding = self.model.encode([query], convert_to_numpy=True)
        return embedding[0].tolist()


# ==========================================
# 3. Vector Database Manager
# ==========================================

class VectorDBManager:
    """
    Manages ChromaDB operations
    
    Responsibilities:
        - Initialize ChromaDB client
        - Create/delete collections
        - Add documents with embeddings
        - Query similar documents
        - Persist database to disk
    """
    
    def __init__(self, db_path: str = "./vector_db", collection_name: str = "emmc_chunks"):
        """
        Initialize ChromaDB manager
        
        Args:
            db_path: Path to persist the database
            collection_name: Name of the collection
        """
        self.db_path = db_path
        self.collection_name = collection_name
        self.client = None
        self.collection = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize ChromaDB persistent client"""
        print(f"Initializing ChromaDB at: {self.db_path}")
        os.makedirs(self.db_path, exist_ok=True)
        self.client = chromadb.PersistentClient(path=self.db_path)
        print("ChromaDB client initialized.")
        
        # Try to load existing collection
        try:
            self.collection = self.client.get_collection(name=self.collection_name)
            print(f"Loaded existing collection '{self.collection_name}'. Count: {self.collection.count()}")
        except Exception:
            print(f"Collection '{self.collection_name}' not found. Use create_collection() to build it.")
    
    def create_collection(self, reset: bool = False):
        """
        Create or get collection
        
        Args:
            reset: If True, delete existing collection and create new one
        """
        if reset:
            try:
                self.client.delete_collection(name=self.collection_name)
                print(f"Deleted existing collection: {self.collection_name}")
            except Exception as e:
                print(f"No existing collection to delete: {e}")
        
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "eMMC protocol chunks with embeddings"}
        )
        print(f"Collection '{self.collection_name}' ready. Current count: {self.collection.count()}")
    
    def add_documents(
        self,
        chunks: List[ChunkData],
        embeddings: List[List[float]],
        batch_size: int = 100
    ):
        """
        Add documents to the collection in batches
        
        Args:
            chunks: List of ChunkData objects
            embeddings: List of embedding vectors
            batch_size: Number of documents to add per batch
        """
        total = len(chunks)
        print(f"Adding {total} documents to collection...")
        
        for i in range(0, total, batch_size):
            batch_chunks = chunks[i:i + batch_size]
            batch_embeddings = embeddings[i:i + batch_size]
            
            # Prepare batch data
            # Use enumeration index for unique IDs (chunk_id may have duplicates)
            ids = [f"chunk_{i + idx}" for idx, chunk in enumerate(batch_chunks)]
            documents = [chunk.content for chunk in batch_chunks]
            metadatas = [
                {
                    "page_num": chunk.page_num,
                    "content_type": chunk.content_type,
                    "caption": chunk.caption,
                    "image_path": chunk.image_path or "",
                    "original_chunk_id": chunk.chunk_id  # Store original ID in metadata
                }
                for chunk in batch_chunks
            ]
            
            # Add to collection
            self.collection.add(
                ids=ids,
                embeddings=batch_embeddings,
                documents=documents,
                metadatas=metadatas
            )
            
            print(f"  Added batch {i // batch_size + 1}/{(total + batch_size - 1) // batch_size}")
        
        print(f"✓ Successfully added {total} documents. Total in collection: {self.collection.count()}")
    
    def query(
        self,
        query_embedding: List[float],
        n_results: int = 5,
        filter_metadata: Optional[Dict] = None
    ) -> List[QueryResult]:
        """
        Query similar documents
        
        Args:
            query_embedding: Query embedding vector
            n_results: Number of results to return
            filter_metadata: Optional metadata filter (e.g., {"content_type": "table"})
            
        Returns:
            List of QueryResult objects
        """
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=filter_metadata
        )
        
        # Parse results into QueryResult objects
        query_results = []
        for i in range(len(results['ids'][0])):
            query_results.append(QueryResult(
                chunk_id=results['ids'][0][i],
                content=results['documents'][0][i],
                distance=results['distances'][0][i],
                metadata=results['metadatas'][0][i],
                page_num=results['metadatas'][0][i]['page_num'],
                content_type=results['metadatas'][0][i]['content_type']
            ))
        
        return query_results


# ==========================================
# 4. Main Pipeline
# ==========================================

class VectorDBPipeline:
    """
    End-to-end pipeline for building vector database
    
    Orchestrates:
        1. Load JSON data
        2. Generate embeddings
        3. Store in ChromaDB
    """
    
    def __init__(
        self,
        json_path: str,
        db_path: str = "./vector_db",
        collection_name: str = "emmc_chunks",
        model_name: str = "all-MiniLM-L6-v2"
    ):
        """
        Initialize pipeline
        
        Args:
            json_path: Path to clean_data.json
            db_path: Path to ChromaDB storage
            collection_name: Collection name
            model_name: Embedding model name
        """
        self.json_path = json_path
        self.embedding_generator = EmbeddingGenerator(model_name)
        self.db_manager = VectorDBManager(db_path, collection_name)
    
    def load_data(self) -> List[ChunkData]:
        """
        Load and validate JSON data
        
        Returns:
            List of ChunkData objects
        """
        print(f"Loading data from: {self.json_path}")
        with open(self.json_path, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
        
        chunks = [ChunkData(**item) for item in raw_data]
        print(f"Loaded {len(chunks)} chunks")
        
        # Statistics
        stats = {}
        for chunk in chunks:
            stats[chunk.content_type] = stats.get(chunk.content_type, 0) + 1
        print(f"  Breakdown: {stats}")
        
        return chunks
    
    def build(self, reset: bool = True):
        """
        Build the vector database
        
        Args:
            reset: If True, reset existing collection
        """
        print("\n" + "="*60)
        print("Building Vector Database")
        print("="*60 + "\n")
        
        # Step 1: Load data
        chunks = self.load_data()
        
        # Step 2: Generate embeddings
        texts = []
        for chunk in chunks:
            if chunk.caption:
                # Prepend caption to content for better semantic retrieval
                text = f"{chunk.caption}\n{chunk.content}"
            else:
                text = chunk.content
            texts.append(text)
        
        embeddings = self.embedding_generator.generate_embeddings(texts)
        
        # Step 3: Create collection
        self.db_manager.create_collection(reset=reset)
        
        # Step 4: Add to database
        self.db_manager.add_documents(chunks, embeddings)
        
        print("\n" + "="*60)
        print("✓ Vector Database Build Complete!")
        print("="*60 + "\n")
    
    def query(self, query_text: str, n_results: int = 5) -> List[QueryResult]:
        """
        Query the vector database
        
        Args:
            query_text: Query string
            n_results: Number of results to return
            
        Returns:
            List of QueryResult objects
        """
        query_embedding = self.embedding_generator.generate_query_embedding(query_text)
        return self.db_manager.query(query_embedding, n_results)


# ==========================================
# 5. Entry Point
# ==========================================

def main():
    """
    Example usage
    """
    # Configuration
    json_path = "./output/clean_data.json"
    db_path = "./vector_db"
    collection_name = "emmc_chunks"
    
    # Build pipeline
    pipeline = VectorDBPipeline(
        json_path=json_path,
        db_path=db_path,
        collection_name=collection_name
    )
    
    # Build database
    pipeline.build(reset=True)
    
    # Example query
    print("\n" + "="*60)
    print("Example Query")
    print("="*60 + "\n")
    
    query = "What are the attributes of Enhanced User Data Area?"
    results = pipeline.query(query, n_results=3)
    
    print(f"Query: {query}\n")
    for i, result in enumerate(results, 1):
        print(f"{i}. [Distance: {result.distance:.4f}] Page {result.page_num} ({result.content_type})")
        print(f"   {result.content[:150]}...")
        print()


if __name__ == "__main__":
    main()

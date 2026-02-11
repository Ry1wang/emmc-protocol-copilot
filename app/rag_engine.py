import sys
import os
from typing import Optional, List, Dict, Any, Generator

# Add parent directory to path so we can import rag_chat_v3
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag_chat_v3 import RAGManager
from app.models import SourceItem

class RAGEngine:
    _instance: Optional['RAGEngine'] = None
    _rag_manager: Optional[RAGManager] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RAGEngine, cls).__new__(cls)
            cls._rag_manager = None
        return cls._instance

    @classmethod
    def get_instance(cls):
        """
        Singleton pattern to ensure models are loaded only once.
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def initialize(self):
        """
        Explicitly initialize the heavy RAGManager (loading models).
        """
        if self._rag_manager is None:
            print("[RAGEngine] Initializing RAGManager (Loading models)...")
            self._rag_manager = RAGManager() # This loads Chroma + CrossEncoder
            print("[RAGEngine] Initialization complete.")

    def chat_stream(self, query: str) -> Generator[Dict[str, Any], None, None]:
        """
        Wrapper around RAGManager.process_query_stream but yields structured data
        for SSE (Server-Sent Events).
        """
        if not self._rag_manager:
            self.initialize()
            
        # Call the underlying stream generator
        for event_type, data in self._rag_manager.process_query_stream(query):
            yield {"type": event_type, "data": data}

    def generate_code_direct(self, args: Dict) -> str:
        """
        Directly generate code without chat context if arguments are known.
        """
        if not self._rag_manager:
            self.initialize()
        return self._rag_manager.generate_code(args)

rag_engine = RAGEngine.get_instance()

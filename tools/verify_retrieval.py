import logging
import sys
from pathlib import Path

# Suppress heavy logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("emmc_copilot")
logger.setLevel(logging.INFO)

from emmc_copilot.retrieval.embedder import BGEEmbedder
from emmc_copilot.retrieval.vectorstore import EMMCVectorStore

questions = [
    "What is Command Queuing (CQ) and how does it improve performance?",
    "Explain the purpose of the Device Health Report.",
    "What is the maximum frequency for HS400 mode and its voltage requirements?",
    "What is the typical Max. Busy Timeout for CMD6 (SWITCH) operations?",
    "Which bit in EXT_CSD is used to enable the Cache function?",
    "How is the C_SIZE field in the CSD register used to calculate device capacity?",
    "Describe the protocol sequence to switch from HS200 to HS400.",
    "What are the power consumption advantages of Sleep Mode compared to Standby State?",
    "If a host sends an invalid Task ID in CQ mode, which status bit reports the error?",
    "How does the Cache Barrier mechanism ensure data consistency during unexpected power loss?"
]

output_file = Path("docs/retrieval_test_v51.md")

def run_verification():
    print("Loading models (this takes a moment)...")
    embedder = BGEEmbedder()
    store = EMMCVectorStore("data/vectorstore/chroma")
    
    with open(output_file, "w") as f:
        f.write("# eMMC 5.1 Pure Vector Retrieval Verification\n\n")
        f.write("Verified using BGE-M3 dense embeddings.\n\n")

    for i, q in enumerate(questions, 1):
        print(f"[{i}/10] Querying: {q}")
        query_vec = embedder.embed_query(q)
        results = store.query(query_vec, n_results=2, where={"version": "5.1"})
        
        with open(output_file, "a") as f:
            f.write(f"## Q{i}: {q}\n\n")
            if not results:
                f.write("> No results found for this query.\n\n")
                continue
                
            for j, res in enumerate(results, 1):
                meta = res["metadata"]
                dist = res["distance"]
                path = meta.get("section_path", "").replace("/", " > ")
                title = meta.get("section_title", "Untitled")
                
                f.write(f"### Hit {j} (Score: {1-dist:.4f})\n")
                f.write(f"- **Source**: {meta['source']} (Page {meta['page_start']})\n")
                f.write(f"- **Path**: {path} > {title}\n\n")
                f.write("```text\n")
                f.write(res["document"][:1000])
                f.write("\n```\n\n")
            f.write("---\n\n")

    print(f"Done. Verfication report: {output_file}")

if __name__ == "__main__":
    run_verification()

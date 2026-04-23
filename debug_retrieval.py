# debug_retrieval.py
import chromadb
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.core import VectorStoreIndex, StorageContext

# Load ChromaDB
client = chromadb.PersistentClient(path="./chroma_db")
collection = client.get_collection("knowledge_base")

# Check what's stored
print(f"Total chunks in DB: {collection.count()}")

# Check metadata of first 5 chunks
results = collection.get(limit=5, include=["metadatas", "documents"])
for i, (meta, doc) in enumerate(zip(results["metadatas"], results["documents"])):
    print(f"\n--- Chunk {i+1} ---")
    print(f"Metadata: {meta}")
    print(f"Preview: {doc[:150]}...")

# Test embedding + retrieval manually
embed_model = HuggingFaceEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
vector_store = ChromaVectorStore(chroma_collection=collection)
storage_context = StorageContext.from_defaults(vector_store=vector_store)
index = VectorStoreIndex.from_vector_store(
    vector_store,
    embed_model=embed_model
)

retriever = index.as_retriever(similarity_top_k=5)
nodes = retriever.retrieve("What is a neural network?")

print(f"\n=== RETRIEVAL TEST ===")
print(f"Chunks retrieved: {len(nodes)}")
for i, node in enumerate(nodes):
    print(f"\nChunk {i+1} | Score: {node.score}")
    print(f"Source: {node.metadata.get('source', 'unknown')}")
    print(f"Preview: {node.text[:200]}...")
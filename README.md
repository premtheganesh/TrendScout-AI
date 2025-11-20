# 🚀 TrendScout AI

AI-powered startup discovery system using hybrid search and knowledge graphs for CSE 573 - Semantic Web Mining.

## 📋 Project Overview

**TrendScout AI** combines classical information retrieval with modern AI/deep learning to discover and analyze AI startups from multiple sources.

### Key Features

- ✅ **Hybrid Search Engine**: Combines keyword (BM25) + semantic (FAISS) search with Reciprocal Rank Fusion
- ✅ **Knowledge Graph**: Neo4j-based entity extraction and relationship mapping  
- ✅ **Vector Embeddings**: E5-base-v2 (768-dimensional) semantic embeddings
- ✅ **LLM Integration**: Groq Llama 3.3 70B for data normalization
- ✅ **Production API**: FastAPI with 7 RESTful endpoints
- ✅ **Cloud Database**: Neo4j Aura for team collaboration
- ✅ **Data Validation**: Pydantic schemas for quality assurance

## 📊 Current Statistics

- **210 Documents**: 140 startups, 20 articles, 50 GitHub repos
- **461 Nodes**: 251 entities extracted via spaCy NER
- **344 Relationships**: With mention counts and importance scores
- **E5 Embeddings**: 768-dimensional vectors in FAISS index

## 🛠️ Tech Stack

- Python 3.13, MongoDB, Neo4j Aura, FAISS
- sentence-transformers (E5-base-v2), spaCy, Groq API
- FastAPI, BeautifulSoup4, Pydantic

## ⚙️ Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure .env (see .env.example)

# Generate embeddings
python scripts/generate_embeddings.py

# Start API
python src/api/main.py
```

Visit: http://localhost:8000/docs

## 📚 Documentation

See `FASTAPI_LEARNING_GUIDE.md` for detailed API documentation.


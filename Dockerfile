# TrendScout AI — API image (Hugging Face Spaces / any container host).
# Indexes are rebuilt from the vectors in MongoDB at boot, so the image
# carries no data. Listens on 7860, the port Spaces expects.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HF_HOME=/tmp/hf \
    INDEX_DIR=/tmp/index INDEX_BUILD_ON_BOOT=true \
    TOKENIZERS_PARALLELISM=false

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements/api.txt requirements/api.txt
RUN pip install --no-cache-dir -r requirements/api.txt

# Bake the embedding model into the image so cold starts do not download 440MB.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/e5-base-v2')"

COPY src ./src
# Host directory modes come along with COPY; the non-root user must be able to read them.
RUN chmod -R a+rX /app/src

# Spaces run as a non-root user with an unwritable /app; everything writable is under /tmp.
RUN useradd -m app && mkdir -p /tmp/index && chown -R app /tmp/index /tmp/hf
USER app

EXPOSE 7860
HEALTHCHECK --interval=60s --timeout=10s --start-period=180s \
    CMD curl -sf http://localhost:7860/health || exit 1

CMD ["python", "-m", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]

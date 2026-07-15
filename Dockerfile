FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    libstdc++6 \
    libglib2.0-0 \
    libgomp1 \
    openssl \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY frontend/dist/ ./frontend/dist/
COPY docker_start.sh .
COPY db_setup.py .

RUN chmod +x docker_start.sh

EXPOSE 8080
CMD ["bash", "docker_start.sh"]

# Pre-download embedding model at build time
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" || true

# Pre-download spaCy model
RUN python -m spacy download en_core_web_sm || true

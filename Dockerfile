FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    libstdc++6 \
    libglib2.0-0 \
    libgomp1 \
    openssl \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download sentence-transformers model (baked into image)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" || true

# Use SMALL spaCy model (12MB not 400MB)
RUN python -m spacy download en_core_web_sm || true

# Copy app
COPY backend/ ./backend/
COPY frontend/dist/ ./frontend/dist/
COPY docker_start.sh .
COPY db_setup.py .

RUN chmod +x docker_start.sh

EXPOSE 8080
CMD ["bash", "docker_start.sh"]

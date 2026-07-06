# =============================================================================
# Contract Intelligence Copilot — Frontend Dockerfile
# Stage 1: Node build (Vite + TypeScript + React)
# Stage 2: nginx runtime (serves static files, proxies API calls)
# =============================================================================

# ── Stage 1: Build ────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

LABEL stage=builder

WORKDIR /app

# Install dependencies first (layer cache — only invalidated if package*.json changes)
COPY package.json package-lock.json ./
RUN npm ci --frozen-lockfile --ignore-scripts

# Copy source and build
COPY . .
RUN npm run build

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

LABEL maintainer="Contract Intelligence Copilot Frontend"

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/app.conf

# Copy built React app
COPY --from=builder /app/dist /usr/share/nginx/html

# nginx runs as non-root by default in alpine image
EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:80 || exit 1

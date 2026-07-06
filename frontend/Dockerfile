# =============================================================================
# Contract Intelligence Copilot — Frontend Dockerfile
# Stage 1: Node build (Vite + TypeScript + React)
# Stage 2: nginx runtime (serves static files)
# =============================================================================

# ── Stage 1: Build ────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

LABEL stage=builder

WORKDIR /app

# Copy package.json first — lockfile is optional (generated if missing)
COPY package.json ./
# Copy lockfile with wildcard so build succeeds even if it doesn't exist yet
COPY package-lock.json* ./

# npm install generates lockfile if missing; npm ci uses it if present
# --ignore-scripts prevents arbitrary postinstall script execution (security)
RUN if [ -f package-lock.json ]; then \
      npm ci --ignore-scripts; \
    else \
      npm install --ignore-scripts; \
    fi

# Copy all source files after dependencies (maximises layer cache)
COPY . .

# Build production bundle
RUN npm run build

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

LABEL maintainer="Contract Intelligence Copilot Frontend"

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Custom nginx config (SPA routing + security headers)
COPY nginx.conf /etc/nginx/conf.d/app.conf

# Copy built React app from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:80 || exit 1

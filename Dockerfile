# ---------- FRONTEND BUILD STAGE ----------
FROM node:20-alpine AS frontend
WORKDIR /app/frontend

# Copy dependency files first for better caching
COPY frontend/package.json frontend/pnpm-lock.yaml* frontend/yarn.lock* frontend/package-lock.json* ./

# Install dependencies (detect lock type automatically)
RUN \
  if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; \
  elif [ -f pnpm-lock.yaml ]; then npm i -g pnpm && pnpm i --frozen-lockfile; \
  elif [ -f yarn.lock ]; then yarn install --frozen-lockfile; \
  else npm i --no-audit --no-fund; fi

# Copy rest of the frontend source
COPY frontend/ ./

# Build the React app (always outputs to /app/frontend/dist)
RUN \
  if [ -f package-lock.json ]; then npm run --silent build; \
  elif [ -f pnpm-lock.yaml ]; then pnpm build; \
  elif [ -f yarn.lock ]; then yarn build; \
  else npm run --silent build; fi


# ---------- BACKEND BUILD STAGE ----------
FROM python:3.11-slim AS backend
WORKDIR /app
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends bash gcc && rm -rf /var/lib/apt/lists/*

# Install backend dependencies
COPY executor/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY executor ./executor

# Copy built frontend assets from the previous stage
COPY --from=frontend /app/frontend/dist ./frontend/dist

EXPOSE 8000

# Launch backend (runs preflight then API)
CMD ["bash", "-c", "python executor/preflight.py && uvicorn executor.api.main:app --host 0.0.0.0 --port 8000"]
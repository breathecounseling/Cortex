# ---- Frontend builder ----
FROM node:20-alpine AS ui
WORKDIR /ui

# Install dependencies
COPY frontend/package*.json ./
RUN npm ci || npm install

# Build
COPY frontend ./
RUN npm run build

# ---- Backend image ----
FROM python:3.11-slim AS backend
WORKDIR /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends bash gcc \
 && rm -rf /var/lib/apt/lists/*

# Python deps
COPY executor/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Source
COPY executor ./executor

# Copy built UI into FastAPI static dir
RUN mkdir -p executor/static/ui
COPY --from=ui /ui/dist/ executor/static/ui/

EXPOSE 8000
CMD ["bash","-c","python executor/preflight.py && uvicorn executor.api.main:app --host 0.0.0.0 --port 8000"]
FROM node:20-alpine AS frontend
WORKDIR /app
# If you already have a frontend, keep these lines; if not, this stage is harmless
COPY frontend/package.json frontend/pnpm-lock.yaml* frontend/yarn.lock* frontend/package-lock.json* ./
RUN \
  if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; \
  elif [ -f pnpm-lock.yaml ]; then npm i -g pnpm && pnpm i --frozen-lockfile; \
  elif [ -f yarn.lock ]; then yarn install --frozen-lockfile; \
  else npm i --no-audit --no-fund; fi
COPY frontend ./frontend
RUN \
  if [ -f package-lock.json ]; then npm run --silent build --prefix ./frontend; \
  elif [ -f pnpm-lock.yaml ]; then pnpm --dir ./frontend build; \
  elif [ -f yarn.lock ]; then yarn --cwd ./frontend build; \
  else npm run --silent build --prefix ./frontend; fi

FROM python:3.11-slim AS backend
WORKDIR /app
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends bash gcc && rm -rf /var/lib/apt/lists/*

COPY executor/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY executor ./executor
# If a frontend was built, copy the assets; otherwise this is a no-op
COPY --from=frontend /app/frontend/dist ./frontend/dist

EXPOSE 8000
CMD ["bash", "-c", "python executor/preflight.py && uvicorn executor.api.main:app --host 0.0.0.0 --port 8000"]
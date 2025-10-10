# PATCH START — Simplify to backend-only build; correct app target
FROM python:3.11-slim AS backend

WORKDIR /app

ENV PYTHONPATH=/app

# Install Python deps
COPY executor/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY executor ./executor

# Expose API port
EXPOSE 8000

# Run preflight checks before starting the API
CMD ["bash", "-c", "python executor/preflight.py && uvicorn executor.api.main:app --host 0.0.0.0 --port 8000"]
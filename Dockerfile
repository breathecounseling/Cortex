# PATCH START — Simplify to backend-only build; correct app target
FROM python:3.11-slim AS backend

WORKDIR /app

# Install Python deps
COPY executor/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY executor ./executor

# Expose API port
EXPOSE 8000

# Correct FastAPI app entrypoint
CMD ["uvicorn", "executor.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
# PATCH END
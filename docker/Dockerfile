# Enterprise Agent OS — Dockerfile
FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install --no-cache-dir fastapi uvicorn sqlalchemy asyncpg pydantic pydantic-settings redis pyjwt passlib python-dotenv structlog httpx tiktoken

# App code
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .

EXPOSE 8000

CMD ["uvicorn", "agent_os.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

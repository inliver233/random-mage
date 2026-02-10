FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN python -m pip install --no-cache-dir --upgrade pip

# Minimal runtime deps (pinned later by dedicated dependency-management issue).
RUN python -m pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    sqlalchemy \
    aiosqlite \
    alembic \
    httpx \
    cryptography

RUN mkdir -p /app/data

COPY backend/app /app/app
COPY backend/alembic.ini /app/alembic.ini
COPY backend/alembic /app/alembic

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


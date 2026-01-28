FROM python:3.12-slim

WORKDIR /app

ENV PYTHONPATH=/app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps (bcrypt) and curl/wget for basic debugging
RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential libffi-dev ca-certificates wget \
  && rm -rf /var/lib/apt/lists/*

# Install uv (single binary)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY requirements.txt ./

# Install dependencies (no lock yet)
RUN uv pip install --system -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

EXPOSE 8080

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8080"]

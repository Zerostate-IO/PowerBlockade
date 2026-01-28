FROM python:3.12-slim

WORKDIR /app

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential libffi-dev ca-certificates wget \
  && rm -rf /var/lib/apt/lists/* \
  && groupadd -g 1000 appuser \
  && useradd -u 1000 -g appuser -m appuser \
  && mkdir -p /shared/rpz /shared/forward-zones \
  && chown -R appuser:appuser /app /shared

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY --chown=appuser:appuser requirements.txt ./
RUN uv pip install --system -r requirements.txt

COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser alembic ./alembic
COPY --chown=appuser:appuser alembic.ini ./alembic.ini

USER appuser

EXPOSE 8080

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8080"]

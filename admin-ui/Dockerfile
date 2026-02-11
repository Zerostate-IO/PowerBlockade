FROM python:3.14-alpine

WORKDIR /app

ARG PB_VERSION=0.4.0
ARG PB_GIT_SHA=unknown
ARG PB_BUILD_DATE=unknown

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PB_VERSION=${PB_VERSION} \
    PB_GIT_SHA=${PB_GIT_SHA} \
    PB_BUILD_DATE=${PB_BUILD_DATE}

LABEL org.opencontainers.image.version="${PB_VERSION}" \
      org.opencontainers.image.revision="${PB_GIT_SHA}" \
      org.opencontainers.image.created="${PB_BUILD_DATE}" \
      org.opencontainers.image.title="PowerBlockade Admin UI" \
      org.opencontainers.image.description="DNS filtering admin interface"

RUN apk add --no-cache build-base libffi-dev ca-certificates wget \
  && addgroup -g 1000 -S appuser \
  && adduser -u 1000 -S -G appuser -h /home/appuser appuser \
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

FROM python:3.12-alpine

WORKDIR /app

ARG PB_VERSION=0.3.2
ARG PB_GIT_SHA=unknown
ARG PB_BUILD_DATE=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PB_VERSION=${PB_VERSION} \
    PB_GIT_SHA=${PB_GIT_SHA}

LABEL org.opencontainers.image.version="${PB_VERSION}" \
      org.opencontainers.image.revision="${PB_GIT_SHA}" \
      org.opencontainers.image.created="${PB_BUILD_DATE}" \
      org.opencontainers.image.title="PowerBlockade sync-agent" \
      org.opencontainers.image.description="Secondary node sync agent for PowerBlockade"

RUN addgroup -g 1000 -S appuser \
  && adduser -u 1000 -S -G appuser -h /home/appuser appuser \
  && chown -R appuser:appuser /app

COPY --chown=appuser:appuser requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser agent.py ./agent.py

USER appuser

CMD ["python", "-u", "agent.py"]

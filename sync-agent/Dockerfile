FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd -g 1000 appuser \
  && useradd -u 1000 -g appuser -m appuser \
  && chown -R appuser:appuser /app

COPY --chown=appuser:appuser requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser agent.py ./agent.py

USER appuser

CMD ["python", "-u", "agent.py"]

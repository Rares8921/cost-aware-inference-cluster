FROM python:3.11.8-slim

# no .pyc folders
# no buffering
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# non user root & dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m appuser

# caching
COPY requirements.txt .

# cache mount for pip
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

COPY services/scheduler/ ./services/scheduler/

# permisiuni user
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8001

CMD ["uvicorn", "services.scheduler.main:app", "--host", "0.0.0.0", "--port", "8001"]
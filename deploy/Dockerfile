FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends clamav clamav-freshclam ca-certificates postgresql-client && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.10.7
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts
COPY alembic.ini ./
COPY deploy/freshclam.conf /app/deploy/freshclam.conf
RUN useradd --uid 10001 --create-home appuser && mkdir -p /app/var/objects /app/var/clamav && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

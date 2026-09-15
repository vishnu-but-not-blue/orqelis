FROM python:3.12-slim
RUN pip install --no-cache-dir uv==0.10.7
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
RUN useradd --uid 10001 --create-home appuser && mkdir -p /app/var/objects && chown -R appuser:appuser /app
USER appuser
CMD ["sh", "-c", "/app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log"]

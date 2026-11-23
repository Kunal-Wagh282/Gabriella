FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.11.11 /uv /usr/local/bin/uv
WORKDIR /app

# Dependencies first for layer caching.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Bake the CLIP text + vision encoders (~0.6 GB) into the image: no runtime downloads,
# and the API and worker never race to fetch them.
ENV MODEL_CACHE_DIR=/opt/models
RUN python -c "from fastembed import TextEmbedding, ImageEmbedding; \
TextEmbedding('Qdrant/clip-ViT-B-32-text', cache_dir='/opt/models'); \
ImageEmbedding('Qdrant/clip-ViT-B-32-vision', cache_dir='/opt/models')"

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY seed ./seed
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh \
    && useradd --create-home --uid 1000 gabriella \
    && mkdir -p /app/media && chown -R gabriella /app/media /opt/models
USER gabriella

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

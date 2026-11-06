FROM ghcr.io/astral-sh/uv:0.9.11 AS uv
FROM python:3.11-slim-bookworm AS dependencies

WORKDIR /app
COPY --from=uv /uv /bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --no-cache

FROM python:3.11-slim-bookworm

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ALCOVE_BIND=0.0.0.0:8000 \
    ALCOVE_DEBUG=0 \
    ALCOVE_DATABASE=/var/lib/alcove/alcove.sqlite3

COPY --from=dependencies /app/.venv .venv
COPY manage.py ./
COPY alcove/ alcove/
COPY config/ config/
COPY deploy/entrypoint.sh deploy/entrypoint.sh
RUN mkdir -p /var/lib/alcove \
    && chown 10001:10001 /var/lib/alcove \
    && ALCOVE_SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput

USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["sh", "deploy/entrypoint.sh"]
CMD ["serve"]

FROM python:3.11-slim

WORKDIR /app

# Install build deps for psycopg2-binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

# Glama only needs the server to start and respond to introspection.
# SAP auth is disabled when no PGP fingerprint is set.
# Postgres is optional — server degrades gracefully without it.
ENV WILLOW_APP_ID=glama-inspect

CMD ["python", "-m", "willow_mcp"]

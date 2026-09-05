# Build the wheel in one stage, run it from a slim image in the next, so no build
# tooling ships in the final layer.
FROM python:3.12-slim AS builder

WORKDIR /build
RUN pip install --no-cache-dir hatchling

COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .


FROM python:3.12-slim

# curl is here for the health check and nothing else.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 forge

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir "$(echo /wheels/*.whl)[dashboard,mcp]" && rm -rf /wheels

ENV EVALFORGE_HOME=/data \
    PYTHONUNBUFFERED=1

RUN mkdir -p /data && chown forge:forge /data
USER forge
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS http://localhost:8000/ || exit 1

CMD ["evalforge", "serve", "--no-browser"]

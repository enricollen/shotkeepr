# syntax=docker/dockerfile:1
ARG RUNTIME=cpu

FROM debian:bookworm-slim AS build
ARG RUNTIME
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_LINK_MODE=copy
WORKDIR /build
COPY pyproject.toml uv.lock ./
COPY packages/core/ packages/core/
COPY packages/plugin-sdk/ packages/plugin-sdk/
COPY packages/desktop/pyproject.toml packages/desktop/pyproject.toml
RUN uv python install 3.12.14 \
    && uv sync --frozen --no-dev --no-editable --package shotkeepr-core --extra "$RUNTIME" --python 3.12.14

FROM debian:bookworm-slim AS cpu
FROM nvidia/cuda:13.0.2-cudnn-runtime-ubuntu22.04 AS cuda

FROM ${RUNTIME} AS runtime
ARG APP_UID=1000
ARG APP_GID=1000
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates libimage-exiftool-perl libstdc++6 libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "$APP_GID" shotkeepr \
    && useradd --uid "$APP_UID" --gid "$APP_GID" --create-home shotkeepr \
    && mkdir -p /data /run/shotkeepr \
    && chown "$APP_UID:$APP_GID" /data /run/shotkeepr
COPY --from=build /opt/python /opt/python
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /home/shotkeepr
USER ${APP_UID}:${APP_GID}
EXPOSE 8321
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD ["shotkeepr-core", "healthcheck", "--port", "8321"]
ENTRYPOINT ["shotkeepr-core"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8321", \
     "--data-dir", "/data", "--runtime-dir", "/run/shotkeepr"]

# syntax=docker/dockerfile:1

########################################
# 1) Build the React UI
########################################
FROM node:22-alpine AS ui-build
WORKDIR /ui
COPY ui/package.json ui/tsconfig.json ui/vite.config.ts ui/index.html ./
RUN npm install --registry=https://registry.npmjs.org
COPY ui/src ./src
RUN npm run build

########################################
# 2) Backend + runtime image
########################################
FROM python:3.13-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg nginx tzdata bash ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --root-user-action=ignore uv

WORKDIR /app
ENV UV_PYTHON_PREFERENCE=only-system \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY pyproject.toml ./
COPY server ./server
RUN uv sync --no-dev

COPY config/config.yml.default ./config/config.yml.default
COPY --from=ui-build /ui/dist /usr/share/nginx/html
COPY .docker/app/nginx.conf /etc/nginx/conf.d/default.conf
RUN rm -f /etc/nginx/sites-enabled/default
COPY .docker/app/scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    TZ=UTC \
    VODLOFT_CONFIG=/config/config.yml \
    VODLOFT_DATABASE_URL=sqlite:////config/vodloft.db \
    VODLOFT_DOWNLOAD_ROOT=/downloads

ARG VODLOFT_VERSION=development
ARG VODLOFT_REVISION=unknown
LABEL org.opencontainers.image.title="VodLoft" \
      org.opencontainers.image.source="https://github.com/samuelvisser/VodLoft" \
      org.opencontainers.image.version="${VODLOFT_VERSION}" \
      org.opencontainers.image.revision="${VODLOFT_REVISION}"

VOLUME ["/config", "/downloads"]
EXPOSE 80
ENTRYPOINT ["/entrypoint.sh"]

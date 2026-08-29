# GeoVision — dashboard image (Module 16).
#
# Build context is dashboard/ (see docker-compose.yml) — self-contained, no
# cross-package dependency the way backend/worker have on ai/.
#
# Vite build -> nginx static serve, with an SPA fallback so a hard refresh on
# a client-side route (e.g. /projects/abc123) doesn't 404 against nginx
# looking for a literal file that doesn't exist.
#
# This nginx is internal only - it serves static files to the *outer* nginx
# (docker/nginx.conf), which is the one actually exposed on :443 and doing TLS
# termination + reverse proxying to both this container and the backend.
#
# syntax=docker/dockerfile:1

FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
    CMD ["wget", "--quiet", "--tries=1", "--spider", "http://127.0.0.1/"]

EXPOSE 80

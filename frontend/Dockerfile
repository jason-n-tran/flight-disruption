# syntax=docker/dockerfile:1

# ---- build stage: produce the static SvelteKit build ----
FROM node:20-alpine AS build
WORKDIR /app

# PUBLIC_* vars are inlined at build time by Vite, so they must be present here.
ARG PUBLIC_API_BASE=http://localhost:8005
ARG PUBLIC_USE_MOCK=false
ENV PUBLIC_API_BASE=$PUBLIC_API_BASE
ENV PUBLIC_USE_MOCK=$PUBLIC_USE_MOCK

COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY . .
RUN npm run build

# ---- serve stage: static files via nginx ----
FROM nginx:alpine AS serve
RUN rm -rf /usr/share/nginx/html/*
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://localhost/ >/dev/null || exit 1
CMD ["nginx", "-g", "daemon off;"]

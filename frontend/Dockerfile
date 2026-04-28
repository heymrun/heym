FROM oven/bun:1 AS builder

WORKDIR /app

COPY frontend/package.json frontend/bun.lock* ./
RUN bun install --frozen-lockfile
COPY VERSION /app/VERSION

COPY frontend/ .
ARG APP_VERSION
ENV APP_VERSION=${APP_VERSION}
ARG VITE_HEYM_WEB_URL=https://heym.run
ENV VITE_HEYM_WEB_URL=${VITE_HEYM_WEB_URL}
RUN bun run build

FROM oven/bun:1

WORKDIR /app

COPY --from=builder /app/dist ./dist
COPY --from=builder /app/package.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/vite.config.ts ./
COPY --from=builder /app/VERSION /app/

EXPOSE 4017

CMD ["bun", "run", "preview", "--host", "0.0.0.0", "--port", "4017"]

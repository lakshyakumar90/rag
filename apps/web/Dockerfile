# syntax=docker/dockerfile:1

# ---- dependencies: pnpm workspace, pnpm 11.25.0 (packageManager) ----
FROM node:26-alpine AS deps
RUN corepack enable && corepack prepare pnpm@11.25.0 --activate
WORKDIR /app
COPY . .
RUN pnpm install --no-frozen-lockfile

# ---- build: Next.js standalone bundle ----
FROM deps AS builder
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost/api/v1
ARG NEXT_PUBLIC_WEB_URL=http://localhost
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_PUBLIC_WEB_URL=${NEXT_PUBLIC_WEB_URL}
RUN pnpm --filter web build

# ---- runtime: non-root, standalone server ----
FROM node:26-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    NEXT_TELEMETRY_DISABLED=1
COPY --chown=node:node --from=builder /app/apps/web/.next/standalone ./
COPY --chown=node:node --from=builder /app/apps/web/.next/static ./apps/web/.next/static
COPY --chown=node:node --from=builder /app/apps/web/public ./apps/web/public
USER node
EXPOSE 3000
CMD ["node", "apps/web/server.js"]

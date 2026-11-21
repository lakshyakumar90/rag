# syntax=docker/dockerfile:1

# ---- dependencies: pnpm workspace, pnpm 11.25.0 (packageManager) ----
FROM node:24-alpine AS deps
RUN corepack enable && corepack prepare pnpm@11.25.0 --activate
WORKDIR /app
COPY . .
RUN pnpm install --no-frozen-lockfile

# ---- build: Next.js standalone bundle ----
FROM deps AS builder
RUN pnpm --filter web build

# ---- runtime: non-root, standalone server ----
FROM node:24-alpine AS runner
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

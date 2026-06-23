# syntax=docker/dockerfile:1

FROM node:22-slim AS deps
WORKDIR /app
ENV PNPM_STORE_DIR=/pnpm/store
RUN corepack enable \
  && pnpm config set store-dir "${PNPM_STORE_DIR}" \
  && pnpm config set fetch-timeout 600000 \
  && pnpm config set fetch-retries 5 \
  && pnpm config set fetch-retry-mintimeout 10000 \
  && pnpm config set fetch-retry-maxtimeout 120000

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN --mount=type=cache,id=academy-manager-frontend-pnpm-store,target=/pnpm/store,sharing=locked \
  pnpm install --frozen-lockfile --prefer-offline

FROM node:22-slim AS builder
WORKDIR /app
RUN corepack enable

COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG BFF_API_ORIGIN=http://backend:8001
ARG NEXT_PUBLIC_API_BASE=/api/v2
ARG NEXT_PUBLIC_FIREBASE_API_KEY=dummy
ARG NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=academy-courtmastr.firebaseapp.com
ARG NEXT_PUBLIC_FIREBASE_PROJECT_ID=academy-courtmastr
ARG NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=academy-courtmastr.firebasestorage.app
ARG NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=953230788846
ARG NEXT_PUBLIC_FIREBASE_APP_ID=1:953230788846:web:1f2819c11418ecf5860bff
ARG NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID=G-Z6GS6WRZY8
# Empty by default so production builds get a no-op falsy value.
# Local SaaS staging passes http://localhost:9099 to wire connectAuthEmulator.
ARG NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST=
# Set to "1" to serve the Firebase sign-in helper first-party from each
# tenant domain (fixes mobile Google sign-in). Requires the OAuth client
# redirect URIs to be registered first — see DEPLOYMENT.md.
ARG NEXT_PUBLIC_FIREBASE_AUTH_PROXY=

ENV BFF_API_ORIGIN=${BFF_API_ORIGIN}
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}
ENV NEXT_PUBLIC_FIREBASE_API_KEY=${NEXT_PUBLIC_FIREBASE_API_KEY}
ENV NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=${NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN}
ENV NEXT_PUBLIC_FIREBASE_PROJECT_ID=${NEXT_PUBLIC_FIREBASE_PROJECT_ID}
ENV NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=${NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET}
ENV NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=${NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID}
ENV NEXT_PUBLIC_FIREBASE_APP_ID=${NEXT_PUBLIC_FIREBASE_APP_ID}
ENV NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID=${NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID}
ENV NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST=${NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST}
ENV NEXT_PUBLIC_FIREBASE_AUTH_PROXY=${NEXT_PUBLIC_FIREBASE_AUTH_PROXY}

RUN pnpm build

FROM node:22-slim AS runner
WORKDIR /app
RUN corepack enable

ENV NODE_ENV=production
ENV PORT=3001
ENV HOSTNAME=0.0.0.0
ENV BFF_API_ORIGIN=http://backend:8001

COPY --from=builder /app ./

EXPOSE 3001
CMD ["pnpm", "start"]

# ── Stage 1: build React app ──────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

# VITE_API_URL is baked in at build time — pass via --build-arg
ARG VITE_API_URL=http://localhost:8002
ARG VITE_PRIVACY_POLICY_URL=https://example.com/privacy
ARG VITE_GA4_ID=

ENV VITE_API_URL=$VITE_API_URL
ENV VITE_PRIVACY_POLICY_URL=$VITE_PRIVACY_POLICY_URL
ENV VITE_GA4_ID=$VITE_GA4_ID

RUN npm run build

# ── Stage 2: serve with nginx ─────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# Remove default nginx content
RUN rm -rf /usr/share/nginx/html/*

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]

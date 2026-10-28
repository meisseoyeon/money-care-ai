# 프런트를 빌드한 뒤, Caddy가 화면 파일을 보여주고 /api 요청은 백엔드로 넘김.
FROM node:22-alpine AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# 같은 주소의 /api로 백엔드를 부름 (Caddy가 백엔드로 전달)
ENV VITE_API_MODE=api VITE_API_BASE_URL=/api
RUN npm run build

FROM caddy:2.8.4-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/dist /srv

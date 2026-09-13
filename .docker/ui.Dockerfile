FROM node:24-bookworm-slim AS build
WORKDIR /app
COPY ui/package.json ui/tsconfig.json ui/vite.config.ts ui/index.html ./
COPY ui/src ./src
RUN npm install && npm run build

FROM nginx:1.29-alpine
COPY .docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80

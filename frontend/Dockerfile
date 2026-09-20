FROM node:22-alpine AS base
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM base AS development
COPY . .
EXPOSE 5173
CMD ["pnpm", "dev"]

FROM base AS build
COPY . .
RUN pnpm build

FROM nginx:1.27-alpine AS production
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80

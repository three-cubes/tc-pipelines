# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 AS uv

FROM python:3.13.15-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26 AS toolchain

ARG TARGETARCH
ARG NODE_VERSION=24.21.0
ARG NODE_SHA256_AMD64=fd8e59d5a511510f6a298afb548f18c7d2b1be404d8b4a27d94fbe49f56cb2d6
ARG NODE_SHA256_ARM64=6ad1325edbdb5649c379b75a237147a666c95d4f9ae8d340fef2d1575d289ad2

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl git make xz-utils \
    && case "$TARGETARCH" in \
         amd64) node_arch=x64; node_sha="$NODE_SHA256_AMD64" ;; \
         arm64) node_arch=arm64; node_sha="$NODE_SHA256_ARM64" ;; \
         *) echo "unsupported TARGETARCH: $TARGETARCH" >&2; exit 1 ;; \
       esac \
    && curl --fail --show-error --silent --location \
         "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" \
         --output /tmp/node.tar.xz \
    && echo "${node_sha}  /tmp/node.tar.xz" | sha256sum --check --strict \
    && tar --extract --xz --file /tmp/node.tar.xz --directory /usr/local --strip-components=1 \
    && rm /tmp/node.tar.xz \
    && corepack disable pnpm \
    && npm install --global pnpm@11.22.0 \
    && apt-get purge --yes --auto-remove curl xz-utils \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

# Package compilation is architecture-neutral and runs on the build host. The
# final toolchain stage below is still built and verified for each target.
FROM --platform=$BUILDPLATFORM python:3.13.15-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26 AS builder
ARG BUILDARCH
ARG NODE_VERSION=24.21.0
ARG NODE_SHA256_AMD64=fd8e59d5a511510f6a298afb548f18c7d2b1be404d8b4a27d94fbe49f56cb2d6
ARG NODE_SHA256_ARM64=6ad1325edbdb5649c379b75a237147a666c95d4f9ae8d340fef2d1575d289ad2
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl git procps xz-utils \
    && case "$BUILDARCH" in \
         amd64) node_arch=x64; node_sha="$NODE_SHA256_AMD64" ;; \
         arm64) node_arch=arm64; node_sha="$NODE_SHA256_ARM64" ;; \
         *) echo "unsupported BUILDARCH: $BUILDARCH" >&2; exit 1 ;; \
       esac \
    && curl --fail --show-error --silent --location \
         "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" \
         --output /tmp/node.tar.xz \
    && echo "${node_sha}  /tmp/node.tar.xz" | sha256sum --check --strict \
    && tar --extract --xz --file /tmp/node.tar.xz --directory /usr/local --strip-components=1 \
    && rm /tmp/node.tar.xz \
    && corepack disable pnpm \
    && npm install --global pnpm@11.22.0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY schemas ./schemas
COPY packages/tc-sdlc ./packages/tc-sdlc
RUN pnpm install --frozen-lockfile \
    && pnpm --filter @three-cubes/tc-sdlc build \
    && pnpm --filter @three-cubes/tc-sdlc pack --pack-destination /tmp/package \
    && npm install --global /tmp/package/three-cubes-tc-sdlc-3.0.0.tgz

FROM builder AS package-tests
RUN pnpm --filter @three-cubes/tc-sdlc test

FROM toolchain
LABEL org.opencontainers.image.source="https://github.com/three-cubes/tc-pipelines" \
      org.opencontainers.image.title="Three Cubes canonical SDLC environment" \
      org.opencontainers.image.version="3.0.0"

RUN groupadd --gid 1000 sdlc \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash sdlc \
    && mkdir --parents /workspace /state \
    && chown --recursive sdlc:sdlc /workspace /state
COPY --from=builder /usr/local/lib/node_modules/@three-cubes /usr/local/lib/node_modules/@three-cubes
RUN ln --symbolic /usr/local/lib/node_modules/@three-cubes/tc-sdlc/dist/cli.js /usr/local/bin/tc-sdlc
COPY images/sdlc/image-marker.json /etc/tc-sdlc-release.json

USER sdlc
WORKDIR /workspace
ENV HOME=/home/sdlc \
    PATH=/usr/local/bin:/usr/bin:/bin
CMD ["tc-sdlc"]

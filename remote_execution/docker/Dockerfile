# syntax=docker/dockerfile:1
# Debian 13 supplies the glibc/GCC ABI used by this repository's Linux fixtures.
# The resulting image ID is also an execution-platform property: rebuilding
# packages changes the remote action keys, even if this Dockerfile is unchanged.
FROM debian:trixie-20261027-slim@sha256:f6b08b09a05725f9431502d3b5714f5c4576e82c1a84fa1debe0c24a7e0c3ec4 AS runtime

ARG NATIVELINK_VERSION=1.8.3
ARG NATIVELINK_SHA256=1a6596c96f059d4e99f7352164321e1f1cdff435275667ad8489e83f7e2977c5

RUN test "$(dpkg --print-architecture)" = amd64 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        bash build-essential ca-certificates curl file git patch pkg-config \
        python3 tar unzip xz-utils zip zstd \
        libegl1 libgl1 libgl1-mesa-dri libglx-mesa0 libgomp1 \
        libice6 libsm6 libx11-6 libxcb1 libxext6 libxfixes3 libxi6 \
        libxkbcommon0 libxrender1 \
        libasound2t64 libatk-bridge2.0-0t64 libatk1.0-0t64 libatspi2.0-0t64 \
        libcairo2 libcups2t64 libdbus-1-3 libdrm2 libgbm1 libglib2.0-0t64 \
        libnspr4 libnss3 libpango-1.0-0 libxcomposite1 libxdamage1 libxrandr2 \
    && rm -rf /var/lib/apt/lists/* \
    && curl --fail --location --retry 3 \
        "https://github.com/TraceMachina/nativelink/releases/download/v${NATIVELINK_VERSION}/nativelink-${NATIVELINK_VERSION}-x86_64-unknown-linux-musl.tar.gz" \
        --output /tmp/nativelink.tar.gz \
    && echo "${NATIVELINK_SHA256}  /tmp/nativelink.tar.gz" | sha256sum --check --strict \
    && tar -xzf /tmp/nativelink.tar.gz -C /usr/local/bin nativelink \
    && mkdir -p /usr/share/doc/nativelink \
    && tar -xzf /tmp/nativelink.tar.gz -C /usr/share/doc/nativelink LICENSE \
    && rm /tmp/nativelink.tar.gz \
    && groupadd --gid 10001 nativelink \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin nativelink \
    && mkdir -p /data/control /data/worker \
    && chown nativelink:nativelink /data/control /data/worker

COPY control.json5 worker.json5 /etc/nativelink/
COPY action-entrypoint.sh /usr/local/bin/nativelink-action
RUN chmod 0755 /usr/local/bin/nativelink-action

ENV LANG=C.UTF-8 LC_ALL=C.UTF-8
USER 10001:10001
WORKDIR /data
ENTRYPOINT ["/usr/local/bin/nativelink"]
CMD ["/etc/nativelink/control.json5"]

# Reindeer's maintenance bootstrap compiles openssl-sys. Keep its headers in
# the CI stage; normal NativeLink workers do not compile the generator.
FROM runtime AS ci
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends libssl-dev \
    && rm -rf /var/lib/apt/lists/*
USER 10001:10001

# Preserve the original worker runtime as the default Docker build target.
FROM runtime AS worker

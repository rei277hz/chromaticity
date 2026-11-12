# Keep CI's local Linux runtime aligned with the shared remote worker packages.
FROM debian:trixie-20261027-slim@sha256:f6b08b09a05725f9431502d3b5714f5c4576e82c1a84fa1debe0c24a7e0c3ec4

RUN test "$(dpkg --print-architecture)" = amd64 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        bash build-essential ca-certificates curl file git libssl-dev patch pkg-config \
        python3 tar texlive-extra-utils texlive-fonts-recommended texlive-lang-chinese \
        texlive-latex-extra texlive-latex-recommended texlive-luatex texlive-xetex \
        unzip xz-utils zip zstd \
        libegl1 libgl1 libgl1-mesa-dri libglx-mesa0 libgomp1 \
        libice6 libsm6 libx11-6 libxcb1 libxext6 libxfixes3 libxi6 \
        libxkbcommon0 libxrender1 \
        libasound2t64 libatk-bridge2.0-0t64 libatk1.0-0t64 libatspi2.0-0t64 \
        libcairo2 libcups2t64 libdbus-1-3 libdrm2 libgbm1 libglib2.0-0t64 \
        libnspr4 libnss3 libpango-1.0-0 libxcomposite1 libxdamage1 libxrandr2 \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=C.UTF-8 LC_ALL=C.UTF-8

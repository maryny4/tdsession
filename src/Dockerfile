FROM --platform=linux/amd64 python:3.13-slim

# System deps: X11 runtime, D-Bus, Fluxbox, fonts, GL
RUN apt-get update && apt-get install -y --no-install-recommends \
    # X11 runtime libs for TDesktop
    libx11-6 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
    libxrandr2 libxrender1 libxtst6 libnss3 libnspr4 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libdrm2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libdbus-1-3 libglib2.0-0 libgtk-3-0 \
    libopengl0 libgl1 libegl1 \
    # KasmVNC undeclared Perl deps (GitHub issue #279)
    ssl-cert xauth x11-xkb-utils xkb-data procps \
    libdatetime-perl libswitch-perl libyaml-tiny-perl \
    libhash-merge-simple-perl liblist-moreutils-perl libtry-tiny-perl \
    # D-Bus + window manager + tools
    dbus dbus-x11 fluxbox xdotool xclip \
    # Build tools + download
    gcc python3-dev curl xz-utils wget \
    # Fonts
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Install Telegram Desktop
RUN curl -fsSL "https://telegram.org/dl/desktop/linux" -o /tmp/tdesktop.tar.xz \
    && mkdir -p /opt/telegram \
    && tar xf /tmp/tdesktop.tar.xz -C /opt/telegram --strip-components=1 \
    && ln -s /opt/telegram/Telegram /usr/local/bin/telegram-desktop \
    && rm /tmp/tdesktop.tar.xz

# Install KasmVNC
ARG KASMVNC_VERSION=1.3.3
RUN wget -qO /tmp/kasmvnc.deb \
    "https://github.com/kasmtech/KasmVNC/releases/download/v${KASMVNC_VERSION}/kasmvncserver_bookworm_${KASMVNC_VERSION}_amd64.deb" \
    && dpkg -i /tmp/kasmvnc.deb || true \
    && apt-get update && apt-get install -fy --no-install-recommends \
    && rm -f /tmp/kasmvnc.deb \
    && rm -rf /var/lib/apt/lists/*

# Python deps: FastAPI + opentele (tdata writer)
# opentele needs PyQt5 (QByteArray for tdata serialization) and telethon (session types)
RUN pip install --no-cache-dir \
    fastapi==0.115.12 \
    "uvicorn[standard]==0.34.2" \
    httpx \
    watchfiles \
    websockets \
    PyQt5 telethon TgCrypto \
    && pip install --no-cache-dir --no-deps opentele

# KasmVNC password (hashed, at build time)
RUN mkdir -p /root/.vnc && \
    printf 'tdsession\ntdsession\n' | vncpasswd -u root -w -r

# XDG runtime dir
RUN mkdir -p /tmp/runtime-root && chmod 700 /tmp/runtime-root
ENV XDG_RUNTIME_DIR=/tmp/runtime-root
ENV DISPLAY=:100

WORKDIR /app

# Copy application
COPY backend/ backend/
COPY frontend/ frontend/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Data dirs
RUN mkdir -p sessions data shared

EXPOSE 6160

ENTRYPOINT ["./entrypoint.sh"]

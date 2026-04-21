FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    SCREEN_GEOMETRY=1280x800x24 \
    VNC_PORT=5900 \
    NOVNC_PORT=6080 \
    PYTHONUNBUFFERED=1 \
    SDL_AUDIODRIVER=dummy \
    PYGAME_HIDE_SUPPORT_PROMPT=1 \
    ALSA_CONFIG_PATH=/dev/null

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        xvfb \
        x11vnc \
        fluxbox \
        novnc \
        websockify \
        fonts-dejavu \
        fontconfig \
        libsdl2-2.0-0 \
        libsdl2-image-2.0-0 \
        libsdl2-mixer-2.0-0 \
        libsdl2-ttf-2.0-0 \
        libfreetype6 \
        libportmidi0 \
        libx11-6 \
        libxext6 \
        libxrender1 \
        libxtst6 \
        libxi6 \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxrandr2 \
        libxcursor1 \
        libasound2 \
        tk \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html \
    && printf '%s\n' '#!/bin/sh' \
        'set -e' \
        'rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true' \
        'Xvfb :99 -screen 0 "$SCREEN_GEOMETRY" -ac +extension GLX +render -noreset >/tmp/xvfb.log 2>&1 &' \
        'sleep 0.6' \
        'fluxbox >/tmp/fluxbox.log 2>&1 &' \
        'x11vnc -display :99 -nopw -forever -shared -rfbport "$VNC_PORT" -quiet >/tmp/x11vnc.log 2>&1 &' \
        'websockify --web /usr/share/novnc "$NOVNC_PORT" "localhost:$VNC_PORT" >/tmp/novnc.log 2>&1 &' \
        'sleep 0.4' \
        'exec "$@"' \
        > /usr/local/bin/atlas-gui-entry \
    && chmod +x /usr/local/bin/atlas-gui-entry

EXPOSE 6080

ENTRYPOINT ["/usr/local/bin/atlas-gui-entry"]

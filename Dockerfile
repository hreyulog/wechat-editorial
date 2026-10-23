FROM node:22-bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PYTHON_BIN=/opt/venv/bin/python3 \
    PATH=/opt/venv/bin:/opt/codex/bin:$PATH CHROME_BINARY=/usr/bin/chromium CODEX_HOME=/runtime/codex PORT=8080 \
    NPM_CONFIG_PREFIX=/opt/codex
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv ffmpeg chromium \
    fonts-noto-cjk fonts-noto-color-emoji ca-certificates git tini nginx openssl \
    xvfb x11vnc websockify novnc openbox dbus-x11 libwebkit2gtk-4.1-0 libayatana-appindicator3-1 \
    && rm -rf /var/lib/apt/lists/* && python3 -m venv /opt/venv
WORKDIR /app
RUN groupadd -g 10001 editorial && useradd -u 10001 -g editorial -m editorial \
    && mkdir -p /runtime/codex /opt/codex && chown editorial:editorial /app /runtime /runtime/codex /opt/codex
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
# Cloud dependencies have a separate file so the portable workstation stays unchanged.
COPY cloud/requirements.txt /tmp/cloud-requirements.txt
RUN pip install --no-cache-dir -r /tmp/cloud-requirements.txt
COPY cloud/install_turbopush.py /tmp/install_turbopush.py
RUN python3 /tmp/install_turbopush.py
COPY --chown=editorial:editorial package.json package-lock.json ./
USER editorial
RUN PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci --omit=dev --no-audit --no-fund \
    && npm install -g @openai/codex@0.164.0
COPY --chown=editorial:editorial . .
RUN python3 cloud/restore_sources.py
EXPOSE 8080
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "-m", "cloud.runtime"]

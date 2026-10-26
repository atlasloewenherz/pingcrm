FROM node:20-slim
# Installed for its runtime shared libraries (libnss3, libatk-bridge2.0-0,
# libgbm1, etc.) only -- the chromium binary itself goes unused. Puppeteer
# pins an exact matched "Chrome for Testing" build per release and downloads
# it below; pointing PUPPETEER_EXECUTABLE_PATH at Debian's own rolling
# chromium package instead (version drifts independently, e.g. apt's 156.x
# against puppeteer-core 24.43.1's pinned 148.x) produces a CDP version skew
# where navigation still works but specific evaluate()/callFunctionOn calls
# -- exactly what whatsapp-web.js polls page state with -- hang instead of
# erroring, rather than failing outright.
#
# unzip is for Puppeteer's own installer below: node:20-slim ships neither
# unzip nor the optional yauzl fallback, so without it the downloaded Chrome
# for Testing archive is fetched successfully but extraction fails and the
# whole npm ci aborts.
RUN apt-get update && apt-get install -y chromium unzip --no-install-recommends && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY src/ ./src/
RUN mkdir -p /data/sessions
EXPOSE 3001
CMD ["node", "src/index.js"]

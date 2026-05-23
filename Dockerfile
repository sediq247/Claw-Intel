#ClawIntel - Production Dockerfile

FROM node:18-slim

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    curl \
    netcat-openbsd \
    bash \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

RUN npm install

RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

RUN chmod +x start.sh

ENV NODE_ENV=production

EXPOSE 3000

CMD ["bash", "start.sh"]
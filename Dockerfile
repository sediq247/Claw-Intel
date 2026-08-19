FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc libffi-dev && rm -rf /var/lib/apt/lists/*


COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY engine_main.py .
COPY index.html .
COPY runtime/ ./runtime/
COPY agents/ ./agents/
COPY utils/ ./utils/
COPY frontend/ ./frontend/

RUN groupadd -r claw && useradd -r -g claw claw && chown -R claw:claw /app
USER claw

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:3000/health', timeout=3)" || exit 1

CMD ["python", "main.py"]

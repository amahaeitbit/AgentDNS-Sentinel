FROM python:3.12-slim

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl nginx unzip \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir \
    "reflex>=0.9,<1" \
    "httpx>=0.27,<1"
COPY dashboard /app/dashboard
COPY demo /app/demo
COPY scripts /app/scripts
COPY rxconfig.py /app/rxconfig.py
COPY dashboard/nginx.conf /etc/nginx/nginx.conf
COPY dashboard/start.sh /app/start.sh
RUN chmod 755 /app/start.sh

EXPOSE 3000
# Nginx provides one tunnel-facing port while Reflex keeps its frontend and
# state backend on their native internal ports.
CMD ["/app/start.sh"]

FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir \
    "dnslib>=0.9.26,<1" \
    "fastapi>=0.115,<1" \
    "uvicorn[standard]>=0.30,<1"
COPY dns_manager /app/dns_manager

EXPOSE 53/udp 8053
CMD ["uvicorn", "dns_manager.api:app", "--host", "0.0.0.0", "--port", "8053"]

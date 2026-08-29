FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir \
    "fastapi>=0.115,<1" \
    "uvicorn[standard]>=0.30,<1"
COPY agents /app/agents

EXPOSE 9000
CMD ["uvicorn", "agents.service:app", "--host", "0.0.0.0", "--port", "9000"]

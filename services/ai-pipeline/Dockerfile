FROM python:3.12-slim

WORKDIR /app/services/ai-pipeline

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY services/ai-pipeline/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY proto /app/proto
RUN python -m grpc_tools.protoc -I /app/proto --python_out=. --grpc_python_out=. /app/proto/resonance.proto

COPY services/ai-pipeline .

EXPOSE 50052

CMD ["python", "main.py"]

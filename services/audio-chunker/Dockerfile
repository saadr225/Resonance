FROM python:3.12-slim

WORKDIR /app/services/audio-chunker

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY services/audio-chunker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY proto /app/proto
RUN python -m grpc_tools.protoc -I /app/proto --python_out=. --grpc_python_out=. /app/proto/resonance.proto

COPY services/audio-chunker .

CMD ["python", "main.py"]

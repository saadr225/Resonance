FROM python:3.12-slim

WORKDIR /app/services/media-server

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libopus0 libvpx9 \
    && rm -rf /var/lib/apt/lists/*

COPY services/media-server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/media-server .

EXPOSE 8080
EXPOSE 9000-9100/udp

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

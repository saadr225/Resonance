FROM python:3.12-slim

WORKDIR /app/services/insight-pusher

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY services/insight-pusher/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/insight-pusher .

EXPOSE 8082

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8082"]

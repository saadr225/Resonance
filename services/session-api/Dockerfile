FROM python:3.12-slim

WORKDIR /app/services/session-api

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY services/session-api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/session-api .

EXPOSE 8083

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8083"]

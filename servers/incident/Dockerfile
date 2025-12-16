FROM python:3.11-slim

WORKDIR /app

RUN pip install fastmcp datadog-api-client requests python-dateutil

COPY incident_server.py .

EXPOSE 8001

CMD ["python", "incident_server.py"]

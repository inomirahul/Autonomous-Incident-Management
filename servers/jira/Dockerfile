FROM python:3.11-slim

WORKDIR /app

RUN pip install fastmcp jira

COPY jira_server.py .

EXPOSE 8003

CMD ["python", "jira_server.py"]

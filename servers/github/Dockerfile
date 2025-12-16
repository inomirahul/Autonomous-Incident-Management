FROM python:3.11-slim

WORKDIR /app

RUN pip install fastmcp PyGithub

COPY github_server.py .

EXPOSE 8002

CMD ["python", "github_server.py"]

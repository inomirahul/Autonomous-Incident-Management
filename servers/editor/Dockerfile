FROM python:3.11-slim

WORKDIR /app

RUN pip install fastmcp whoosh filelock python-magic

COPY editor.py .

EXPOSE 8006

CMD ["python", "editor.py"]

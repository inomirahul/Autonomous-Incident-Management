FROM python:3.11-slim

WORKDIR /app

RUN pip install fastmcp whoosh filelock python-magic

COPY file.py .

EXPOSE 8005

CMD ["python", "file.py"]

FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastmcp psycopg2-binary

COPY . .

RUN chmod +x db_setup.sh

EXPOSE 8004

CMD ["python", "memory_server.py"]

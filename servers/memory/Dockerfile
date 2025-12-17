FROM python:3.11-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install fastmcp psycopg2-binary

COPY . .

RUN chmod +x db_setup.sh

EXPOSE 8004

CMD ["python", "memory_server.py"]

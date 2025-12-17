FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ripgrep \
        openssh-server \
        git \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install fastmcp whoosh filelock python-magic

COPY shell.py .
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

EXPOSE 8007

ENTRYPOINT ["/entrypoint.sh"]

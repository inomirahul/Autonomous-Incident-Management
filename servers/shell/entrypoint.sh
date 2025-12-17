#!/bin/sh
set -e

printf "machine github.com\nlogin x-access-token\npassword %s\n" "$GITHUB_TOKEN" > /root/.netrc
chmod 600 /root/.netrc

exec python /app/shell.py

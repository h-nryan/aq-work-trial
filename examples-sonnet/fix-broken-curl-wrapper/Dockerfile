FROM ubuntu:24.04

RUN apt-get update && apt-get install -y tmux asciinema curl python3 python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY curl_wrapper.py /app/
COPY requirements.txt /app/

RUN chmod +x /app/curl_wrapper.py

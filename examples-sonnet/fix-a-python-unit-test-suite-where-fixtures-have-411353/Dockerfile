FROM tbench-base:latest
WORKDIR /app

COPY test_fixtures.py /app/
COPY conftest.py /app/
COPY run-tests.sh /app/
RUN chmod +x /app/run-tests.sh

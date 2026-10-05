# Tablekeeper stage 2: Python 3.12 standard library plus the IANA tz database (tzdata).
# Everything is installed at build time; nothing is fetched at run time.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONTZPATH="" \
    PORT=8080

# PYTHONTZPATH="" makes zoneinfo use only this pinned tz database, not the OS copy.
RUN pip install --no-cache-dir tzdata==2025.3

WORKDIR /app
COPY tablekeeper ./tablekeeper

EXPOSE 8080
CMD ["python", "-m", "tablekeeper"]

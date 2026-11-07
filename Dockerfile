# Every dependency ships a wheel for this Python, so the image needs no
# compiler. --only-binary makes the build fail rather than compile one that
# stops shipping a wheel.
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt

COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

COPY smartthings_ws/ smartthings_ws/
COPY main.py .
COPY config.yaml .

# The application listens above 1024 and only opens ordinary UDP sockets.
RUN useradd --create-home --uid 10001 smartthings
USER smartthings

# Deliberately not an ENV: the environment takes precedence over the
# configuration file, so an ENV here would override the port of a mounted file.
EXPOSE 8124

# /health needs no token, so the probe works with authorisation enabled.
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD ["python3", "-m", "smartthings_ws.probe"]

ENTRYPOINT ["./entrypoint.sh"]

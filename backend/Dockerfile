FROM python:3.11-slim
ARG WEB_API_PORT
ENV GUNICORN_CMD_ARGS="--bind 0.0.0.0:5000 --timeout 120 --log-level debug --error-logfile - --access-logfile - --capture-output"
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# expects a /health endpoint in Flask for healthcheck
CMD ["gunicorn", "app:create_app()"]
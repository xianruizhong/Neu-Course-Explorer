FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY api/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy app + frontend
COPY api/ api/
COPY web/ web/

EXPOSE 8080

ENV DB_PATH=/data/courses.db
ENV WEB_DIR=/app/web

CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]

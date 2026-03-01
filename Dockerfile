FROM python:3.12-slim

# Install dependencies
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all files
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Create data directory for SQLite
RUN mkdir -p /data

# Set env defaults
ENV DATABASE_PATH=/data/rates.db
ENV PORT=8000
ENV PYTHONPATH=/app/backend

# Run from backend dir so imports work
WORKDIR /app/backend
CMD uvicorn api:app --host 0.0.0.0 --port ${PORT}

FROM python:3.12-slim

WORKDIR /app

# Install dependencies (includes uvicorn for local server)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt uvicorn[standard]

# Copy application source
COPY handler.py main.py exceptions.py db.py cache.py models.py ./
COPY routers/ ./routers/

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

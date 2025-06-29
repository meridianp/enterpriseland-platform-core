FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash platform && \
    chown -R platform:platform /app
USER platform

# Run migrations and start server
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "platform_core.wsgi:application"]

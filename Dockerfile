FROM python:3.11-slim

WORKDIR /app

# Install dependencies for plyvel (LevelDB) to read Claude Desktop cache
RUN apt-get update && apt-get install -y \
    build-essential \
    libleveldb-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-u", "collector.py"]

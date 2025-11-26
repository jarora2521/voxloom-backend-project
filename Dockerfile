# Dockerfile (dev)
FROM python:3.11-slim
WORKDIR /app

# system deps (if needed)
RUN apt-get update && apt-get install -y build-essential ffmpeg && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DATABASE_URL=sqlite+aiosqlite:///./voxloom.db
ENV API_KEY=voxloom_demo_api_key

VOLUME [ "/app/media" ]
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

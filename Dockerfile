FROM python:3.12-slim-bookworm

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && patchright install --with-deps chrome \
 && rm -rf /var/lib/apt/lists/*

COPY watch.py .
COPY restock/ restock/

# Mount a volume here so watches.json survives container rebuilds.
ENV RESTOCK_WATCHES=/data/watches.json \
    RESTOCK_PROFILE_DIR=/data/chrome-profile \
    PYTHONUNBUFFERED=1
VOLUME /data

ENTRYPOINT ["python", "watch.py"]
CMD ["run"]

# AERION-X backend + GUI container. CPU-only (no CUDA base image) — matches
# every performance number measured in this project, which were all CPU-only.
# A GPU-enabled variant would need a CUDA base image and the GPU-enabled torch
# wheel index, neither of which has been built or tested here.
FROM python:3.12-slim

# opencv needs these at runtime even in headless mode
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# torch AND torchvision must come from the same CPU wheel index together —
# installing torch here and letting requirements.txt's later `pip install`
# pull torchvision from default PyPI (whatever CUDA build it resolves to)
# produces an ABI mismatch: ultralytics fails at runtime with
# "operator torchvision::nms does not exist" (found by actually running a
# pipeline in the built container, not by inspecting the Dockerfile).
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision \
    && pip install --no-cache-dir -r requirements.txt

COPY core/ core/
COPY adapters/ adapters/
COPY backend/ backend/
COPY frontend/ frontend/
COPY scripts/ scripts/

RUN mkdir -p data/db data/sensors data/reports data/backups
# Includes the ~8MB demo test video (data/videos/vtest.avi, BSD-licensed
# OpenCV sample) so the pipeline is demoable out of the box.
COPY data/videos/ data/videos/

EXPOSE 8000

# YOLOv8n/YOLOv8n-pose weights download on first use (~6MB each) unless
# pre-baked into the image — not done here, so first pipeline run in a fresh
# container needs outbound internet once.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

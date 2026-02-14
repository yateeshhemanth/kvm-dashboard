FROM python:3.11-slim
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libvirt-clients openssh-client qemu-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agent.py .
COPY app ./app
EXPOSE 9090
CMD ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "9090"]

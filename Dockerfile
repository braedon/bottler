FROM python:3.8-slim

WORKDIR /site

RUN apt-get update \
    && apt-get install -y git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /site/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY utils/*.py /site/utils/
COPY main.py /site/
COPY README.md /site/

ENTRYPOINT ["python", "-u", "main.py"]

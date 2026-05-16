FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    THREEDTREES_METADATA_REFERENCE_DIR=/reference-data

WORKDIR /src

COPY requirements.txt ./
COPY src/ /src/
COPY reference-data/ /reference-data/

RUN pip install --no-cache-dir -r requirements.txt && \
    chmod -R a+rX /src /reference-data

ENTRYPOINT ["python", "run.py"]
CMD ["--help"]

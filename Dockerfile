FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libexpat1 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /in /out /src /reference-data && chmod 777 /in /out /src /reference-data

RUN pip install --no-cache-dir \
    fiona \
    pyproj \
    shapely

COPY src/ /src/
COPY reference-data/ /reference-data/
RUN chmod -R a+rX /src
RUN chmod -R a+rX /reference-data

ENV THREEDTREES_METADATA_REFERENCE_DIR=/reference-data

WORKDIR /src
CMD ["python", "run.py", "--help"]

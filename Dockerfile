FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libexpat1 \
    unzip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /in /out /src /reference-data/gadm /reference-data/ecoregion && chmod 777 /in /out /src /reference-data

RUN curl -L "https://geodata.ucdavis.edu/gadm/gadm4.1/gadm_410-gpkg.zip" -o /reference-data/gadm/gadm_410-gpkg.zip
RUN unzip -q /reference-data/gadm/gadm_410-gpkg.zip -d /reference-data/gadm && rm /reference-data/gadm/gadm_410-gpkg.zip
RUN curl -L "https://c402277.ssl.cf1.rackcdn.com/publications/15/files/original/official_teow.zip?1349272619" -o /reference-data/ecoregion/official_teow.zip
RUN unzip -q /reference-data/ecoregion/official_teow.zip -d /reference-data/ecoregion && rm /reference-data/ecoregion/official_teow.zip

RUN pip install --no-cache-dir \
    fiona \
    "laspy[lazrs]" \
    pyproj \
    shapely

COPY src/ /src/
RUN chmod -R a+rX /src
RUN chmod -R a+rX /reference-data

ENV THREEDTREES_METADATA_REFERENCE_DIR=/reference-data

WORKDIR /src
CMD ["python", "run.py", "--help"]

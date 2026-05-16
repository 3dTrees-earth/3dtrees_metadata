FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libexpat1 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /in /out /src && chmod 777 /in /out /src

RUN pip install --no-cache-dir \
    fiona \
    pyproj \
    shapely

COPY src/ /src/
RUN chmod -R a+rX /src

WORKDIR /src
CMD ["python", "run.py", "--help"]

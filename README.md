# 3Dtrees Metadata Tool

Extract administrative and ecoregion context for a point-cloud collection
summary.

The Python tool reads `collection_summary.json` from the standardization
collection workflow, resolves the WGS84 centroid, and looks that point up in
reference vector datasets stored in the Docker image. If the summary already
contains centroid longitude/latitude values, those are used directly. Otherwise,
the tool falls back to computing the centroid from `collection.multipolygon_wkt`.
If neither is available and `--pointcloud` is supplied, the tool derives the
centroid from the LAS/LAZ header bounds without reading point records.

GADM provides administrative boundary attributes. WWF Terrestrial Ecoregions
v2.0 provides ecoregion, realm, and biome attributes. The tool returns matched
source fields without deriving forest, land-cover, or biome-class flags. Blank
source values are emitted as JSON `null` so unavailable fields remain visible in
the output. The flat GADM `raw_fields` object is preserved, and the same
administrative fields are also exposed as structured `levels` from `0` through
`5`. When GADM is requested but no feature matches, `raw_fields` and `levels` are
still emitted with known administrative fields set to JSON `null`.

## Inputs

- `--collection-summary`: JSON file produced by `tool_standard` collection mode.
  The centroid can be supplied as `collection.centroid`, top-level `centroid`,
  or key/value metadata with longitude/latitude aliases such as `lon`/`lat` or
  `x`/`y`.
- `--pointcloud`: Optional LAS/LAZ fallback used only when the collection
  summary has no centroid and no `collection.multipolygon_wkt`. Only header
  bounds are read.
- `--metadata-layers`: Comma-separated layer list. Supported values are `gadm`
  and `ecoregion`.
- `--reference-data-dir`: Directory containing reference data inside the Docker
  image. Defaults to `/reference-data`.
- `--gadm-path`: Optional override for the GADM vector dataset, usually a
  `.gpkg` or `.shp`.
- `--gadm-layer`: Optional layer name. If omitted for a multi-layer dataset, all
  layers are checked.
- `--wwf-ecoregions-path`: Optional override for the WWF Terrestrial Ecoregions
  v2.0 vector dataset, usually `wwf_terr_ecos.shp`.
- `--wwf-ecoregions-layer`: Optional WWF layer name. If omitted, all layers are
  checked.

The Docker image downloads the production reference data at build time into
`/reference-data/gadm` and `/reference-data/ecoregion`. The checked-in
`reference-data` files are small fixtures for local tests only.

## Output

Default output is `additional_metadata.json`.

```json
{
  "lookup": {
    "centroid": {
      "longitude": 7.85,
      "latitude": 47.99,
      "crs": "EPSG:4326",
      "method": "collection.centroid"
    },
    "reference_layers_checked": [
      {
        "metadata_layer": "gadm",
        "dataset": "GADM",
        "path": "gadm41_DEU.gpkg",
        "layers_checked": ["ADM_ADM_0", "ADM_ADM_1"]
      },
      {
        "metadata_layer": "ecoregion",
        "dataset": "WWF Terrestrial Ecoregions v2.0",
        "path": "wwf_terr_ecos.shp",
        "layers_checked": ["wwf_terr_ecos"]
      }
    ]
  },
  "admin": {
    "matched": true,
    "selected_layer": "ADM_ADM_1",
    "match_count": 1,
    "raw_fields": {
      "GID_0": "DEU",
      "COUNTRY": "Germany",
      "GID_1": "DEU.1_1",
      "NAME_1": "Baden-Wuerttemberg",
      "GID_2": null,
      "GID_5": null,
      "NAME_5": null,
      "CC_5": null,
      "TYPE_5": null,
      "ENGTYPE_5": null
    },
    "levels": {
      "0": {
        "GID_0": "DEU",
        "NAME_0": "Germany",
        "VARNAME_0": null,
        "COUNTRY": "Germany",
        "CONTINENT": "Europe",
        "SUBCONT": null,
        "SOVEREIGN": "Germany",
        "GOVERNEDBY": null,
        "DISPUTEDBY": null,
        "REGION": null,
        "VARREGION": null
      },
      "1": {
        "GID_1": "DEU.1_1",
        "NAME_1": "Baden-Wuerttemberg",
        "VARNAME_1": null,
        "NL_NAME_1": null,
        "ISO_1": null,
        "HASC_1": "DE.BW",
        "CC_1": "08",
        "TYPE_1": "Land",
        "ENGTYPE_1": "State",
        "VALIDFR_1": "Unknown"
      },
      "2": {
        "GID_2": null,
        "NAME_2": null,
        "VARNAME_2": null,
        "NL_NAME_2": null,
        "HASC_2": null,
        "CC_2": null,
        "TYPE_2": null,
        "ENGTYPE_2": null,
        "VALIDFR_2": null
      },
      "3": {
        "GID_3": null,
        "NAME_3": null,
        "VARNAME_3": null,
        "NL_NAME_3": null,
        "HASC_3": null,
        "CC_3": null,
        "TYPE_3": null,
        "ENGTYPE_3": null,
        "VALIDFR_3": null
      },
      "4": {
        "GID_4": null,
        "NAME_4": null,
        "VARNAME_4": null,
        "CC_4": null,
        "TYPE_4": null,
        "ENGTYPE_4": null,
        "VALIDFR_4": null
      },
      "5": {
        "GID_5": null,
        "NAME_5": null,
        "CC_5": null,
        "TYPE_5": null,
        "ENGTYPE_5": null
      }
    }
  },
  "ecoregion": {
    "matched": true,
    "selected_layer": "wwf_terr_ecos",
    "match_count": 1,
    "raw_fields": {
      "ECO_NAME": "Black Forest",
      "ECO_ID": "PA0414",
      "REALM": "PA",
      "BIOME": 4
    }
  }
}
```

## Example

Chained after standardization collection mode:

```bash
python src/run.py \
  --collection-summary /standardization-out/collection_summary.json \
  --metadata-layers gadm,ecoregion \
  --output-file /out/additional_metadata.json
```

The metadata tool must consume the actual `collection_summary.json` produced by
standardization in end-to-end tests. This keeps centroid ownership in
standardization and metadata enrichment ownership here.

```bash
python src/run.py \
  --collection-summary /in/collection_summary.json \
  --metadata-layers gadm,ecoregion \
  --output-file /out/additional_metadata.json
```

Docker:

```bash
docker build -t 3dtrees-metadata .
docker run --rm \
  -v "$PWD/in:/in:ro" \
  -v "$PWD/out:/out" \
  3dtrees-metadata \
  python /src/run.py \
  --collection-summary /in/collection_summary.json \
  --metadata-layers gadm,ecoregion \
  --output-file /out/additional_metadata.json
```

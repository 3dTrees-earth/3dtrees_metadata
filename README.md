# 3Dtrees Metadata Tool

Extract administrative and ecoregion context for a point-cloud collection
summary.

The Python tool reads `collection_summary.json` from the standardization
collection workflow, takes `collection.multipolygon_wkt`, computes the WGS84
centroid, and looks that point up in reference vector datasets stored in the
Docker image.

GADM provides administrative boundaries only. It does not contain forest biome
or land-cover information. WWF Terrestrial Ecoregions v2.0 provides the
ecoregion, realm, and biome context.

## Inputs

- `--collection-summary`: JSON file produced by `tool_standard` collection mode.
- `--metadata-layers`: Comma-separated layer list. Supported values are `gadm`
  and `ecoregion`.
- `--reference-data-dir`: Directory containing reference data inside the Docker
  image. Defaults to `/reference-data`.
- `--gadm-path`: Optional override for the GADM vector dataset, usually a
  `.gpkg` or `.shp`.
- `--gadm-layer`: Optional layer name. If omitted for a multi-layer dataset, all
  layers are checked and the deepest matching administrative level is selected.
- `--wwf-ecoregions-path`: Optional override for the WWF Terrestrial Ecoregions
  v2.0 vector dataset, usually `wwf_terr_ecos.shp`.
- `--wwf-ecoregions-layer`: Optional WWF layer name. If omitted, all layers are
  checked.

The Docker image expects reference data under `/reference-data/gadm` and
`/reference-data/ecoregion`. The checked-in files are small test fixtures. For a
production image, replace them with the real GADM and WWF datasets before
building. GADM licensing does not allow redistribution without permission, so
public images should only bundle GADM data if the redistribution terms are
cleared.

## Output

Default output is `additional_metadata.json`.

```json
{
  "admin": {
    "source": {
      "dataset": "GADM",
      "path": "gadm41_DEU.gpkg",
      "layers_checked": ["ADM_ADM_0", "ADM_ADM_1"]
    },
    "centroid": {
      "longitude": 7.85,
      "latitude": 47.99,
      "crs": "EPSG:4326",
      "method": "shapely.centroid(collection.multipolygon_wkt)"
    },
    "matched": true,
    "selected_layer": "ADM_ADM_1",
    "selected_level": 1,
    "admin_levels": [
      {"level": 0, "gid": "DEU", "name": "Germany"},
      {"level": 1, "gid": "DEU.1_1", "name": "Baden-Wuerttemberg"}
    ],
    "raw_fields": {
      "GID_0": "DEU",
      "COUNTRY": "Germany",
      "GID_1": "DEU.1_1",
      "NAME_1": "Baden-Wuerttemberg"
    }
  },
  "ecoregion": {
    "source": {
      "dataset": "WWF Terrestrial Ecoregions v2.0",
      "path": "wwf_terr_ecos.shp",
      "layers_checked": ["wwf_terr_ecos"]
    },
    "matched": true,
    "selected_layer": "wwf_terr_ecos",
    "ecoregion_name": "Black Forest",
    "ecoregion_id": "PA0414",
    "realm": "PA",
    "biome_code": 4,
    "biome_name": "Temperate Broadleaf & Mixed Forests",
    "is_forest_biome": true,
    "raw_fields": {
      "ECO_NAME": "Black Forest",
      "REALM": "PA",
      "BIOME": 4
    }
  }
}
```

## Example

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

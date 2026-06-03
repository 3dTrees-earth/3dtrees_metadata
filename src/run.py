#!/usr/bin/env python3
"""Extract administrative and ecoregion metadata for a 3Dtrees collection summary."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any, Callable

import fiona
import laspy
from pyproj import CRS, Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform
from shapely import wkt


SUPPORTED_METADATA_LAYERS = ("gadm", "ecoregion")
DEFAULT_REFERENCE_DATA_DIR = "/reference-data"
CENTROID_KEYS = ("centroid", "center", "centre", "centorid")
GADM_LEVEL_FIELDS = {
    0: (
        "GID_0",
        "NAME_0",
        "VARNAME_0",
        "COUNTRY",
        "CONTINENT",
        "SUBCONT",
        "SOVEREIGN",
        "GOVERNEDBY",
        "DISPUTEDBY",
        "REGION",
        "VARREGION",
    ),
    1: (
        "GID_1",
        "NAME_1",
        "VARNAME_1",
        "NL_NAME_1",
        "ISO_1",
        "HASC_1",
        "CC_1",
        "TYPE_1",
        "ENGTYPE_1",
        "VALIDFR_1",
    ),
    2: (
        "GID_2",
        "NAME_2",
        "VARNAME_2",
        "NL_NAME_2",
        "HASC_2",
        "CC_2",
        "TYPE_2",
        "ENGTYPE_2",
        "VALIDFR_2",
    ),
    3: (
        "GID_3",
        "NAME_3",
        "VARNAME_3",
        "NL_NAME_3",
        "HASC_3",
        "CC_3",
        "TYPE_3",
        "ENGTYPE_3",
        "VALIDFR_3",
    ),
    4: (
        "GID_4",
        "NAME_4",
        "VARNAME_4",
        "CC_4",
        "TYPE_4",
        "ENGTYPE_4",
        "VALIDFR_4",
    ),
    5: (
        "GID_5",
        "NAME_5",
        "CC_5",
        "TYPE_5",
        "ENGTYPE_5",
    ),
}

REFERENCE_DATASETS = {
    "gadm": {
        "path_arg": "gadm_path",
        "preferred_names": ("gadm_410.gpkg", "gadm.gpkg", "gadm_fixture.geojson"),
        "extensions": (".gpkg", ".geojson", ".shp"),
    },
    "ecoregion": {
        "path_arg": "wwf_ecoregions_path",
        "preferred_names": (
            "wwf_terr_ecos.shp",
            "wwf_terr_ecos.gpkg",
            "wwf_ecoregions.geojson",
            "wwf_ecoregions_fixture.geojson",
        ),
        "extensions": (".shp", ".gpkg", ".geojson"),
    },
}


def parse_metadata_layers(raw_value: str) -> list[str]:
    normalized = (
        raw_value.replace("[", "")
        .replace("]", "")
        .replace("'", "")
        .replace('"', "")
        .replace(" ", "")
    )
    layers = [layer for layer in normalized.split(",") if layer]
    invalid_layers = [layer for layer in layers if layer not in SUPPORTED_METADATA_LAYERS]
    if invalid_layers:
        raise ValueError(
            "Unsupported metadata layer(s): "
            f"{', '.join(invalid_layers)}. Supported layers: "
            f"{', '.join(SUPPORTED_METADATA_LAYERS)}"
        )
    return layers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="3Dtrees metadata tool: GADM and WWF ecoregion lookup"
    )
    parser.add_argument(
        "--collection-summary",
        "--collection_summary",
        "--input",
        dest="collection_summary",
        required=True,
        help="collection_summary.json produced by tool_standard collection mode",
    )
    parser.add_argument(
        "--metadata-layers",
        "--metadata_layers",
        dest="metadata_layers",
        default="",
        help="Comma-separated metadata layers to extract: gadm,ecoregion",
    )
    parser.add_argument(
        "--pointcloud",
        "--point-cloud",
        "--point_cloud",
        dest="pointcloud",
        default="",
        help=(
            "Optional LAS/LAZ point cloud used only as a centroid fallback. "
            "Only header bounds are read."
        ),
    )
    parser.add_argument(
        "--reference-data-dir",
        "--reference_data_dir",
        dest="reference_data_dir",
        default=os.environ.get(
            "THREEDTREES_METADATA_REFERENCE_DIR", DEFAULT_REFERENCE_DATA_DIR
        ),
        help="Directory containing reference datasets bundled in the Docker image.",
    )
    parser.add_argument(
        "--gadm-path",
        "--gadm_path",
        dest="gadm_path",
        default="",
        help="GADM vector dataset path, for example a .gpkg or .shp",
    )
    parser.add_argument(
        "--gadm-layer",
        "--gadm_layer",
        dest="gadm_layer",
        default="",
        help="Optional GADM layer name. If omitted, all layers are checked.",
    )
    parser.add_argument(
        "--wwf-ecoregions-path",
        "--wwf_ecoregions_path",
        "--wwf-path",
        "--wwf_path",
        dest="wwf_ecoregions_path",
        default="",
        help=(
            "Optional WWF Terrestrial Ecoregions v2.0 vector dataset path, "
            "for example wwf_terr_ecos.shp"
        ),
    )
    parser.add_argument(
        "--wwf-ecoregions-layer",
        "--wwf_ecoregions_layer",
        "--wwf-layer",
        "--wwf_layer",
        dest="wwf_ecoregions_layer",
        default="",
        help="Optional WWF ecoregions layer name. If omitted, all layers are checked.",
    )
    parser.add_argument(
        "--output-file",
        "--output_file",
        dest="output_file",
        default="",
        help="Output JSON path. Defaults to <output-dir>/additional_metadata.json.",
    )
    parser.add_argument(
        "--output-dir",
        "--output_dir",
        dest="output_dir",
        default="/out",
        help="Output directory used when --output-file is not set",
    )

    args = parser.parse_args()

    collection_summary = Path(args.collection_summary)
    if not collection_summary.exists():
        parser.error(f"Collection summary does not exist: {collection_summary}")
    if args.pointcloud and not Path(args.pointcloud).exists():
        parser.error(f"Point cloud does not exist: {args.pointcloud}")
    try:
        selected_layers = parse_metadata_layers(args.metadata_layers)
    except ValueError as exc:
        parser.error(str(exc))

    if not selected_layers:
        selected_layers = []
        if args.gadm_path:
            selected_layers.append("gadm")
        if args.wwf_ecoregions_path:
            selected_layers.append("ecoregion")

    if not selected_layers:
        parser.error("At least one metadata layer is required: gadm or ecoregion")

    args.metadata_layers = selected_layers

    if args.output_file:
        output_file = Path(args.output_file)
    else:
        output_file = Path(args.output_dir) / "additional_metadata.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file = str(output_file)

    return args


def reference_data_dir(args: argparse.Namespace, layer: str) -> Path:
    return Path(args.reference_data_dir) / layer


def find_reference_file(
    search_dir: Path, preferred_names: tuple[str, ...], extensions: tuple[str, ...]
) -> Path | None:
    if not search_dir.exists():
        return None

    for preferred_name in preferred_names:
        matches = list(search_dir.rglob(preferred_name))
        if matches:
            return matches[0]

    for extension in extensions:
        matches = sorted(search_dir.rglob(f"*{extension}"))
        if matches:
            return matches[0]

    return None


def resolve_reference_dataset(args: argparse.Namespace, layer: str) -> str:
    config = REFERENCE_DATASETS[layer]
    explicit_path = getattr(args, str(config["path_arg"]))
    if explicit_path:
        path = Path(explicit_path)
        if not path.exists():
            raise FileNotFoundError(f"{layer} reference path does not exist: {path}")
        return str(path)

    root_dir = Path(args.reference_data_dir)
    layer_dir = reference_data_dir(args, layer)
    for search_dir in (layer_dir, root_dir):
        reference_file = find_reference_file(
            search_dir,
            config["preferred_names"],  # type: ignore[arg-type]
            config["extensions"],  # type: ignore[arg-type]
        )
        if reference_file is not None:
            return str(reference_file)

    raise FileNotFoundError(
        f"Could not find a usable {layer} vector dataset in {layer_dir}. "
        "Reference data must be bundled in the Docker image under /reference-data "
        "or passed explicitly with the layer path argument."
    )


def read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_mapping_keys(value: dict[str, Any]) -> dict[str, Any]:
    return {str(key).strip().lower(): item for key, item in value.items()}


def key_value_list_to_mapping(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, list):
        return None

    pairs: dict[str, Any] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        if "key" not in item or "value" not in item:
            continue
        key = str(item["key"]).strip().lower()
        if key:
            pairs[key] = item["value"]

    return pairs or None


def value_from_aliases(mapping: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    normalized = normalize_mapping_keys(mapping)
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    return None


def point_from_lon_lat(lon_value: Any, lat_value: Any) -> Point | None:
    longitude = as_float(lon_value)
    latitude = as_float(lat_value)
    if longitude is None or latitude is None:
        return None
    return Point(longitude, latitude)


def point_from_centroid_value(value: Any) -> Point | None:
    if isinstance(value, dict):
        mapping = normalize_mapping_keys(value)
        if "key" in mapping and "value" in mapping:
            if str(mapping["key"]).strip().lower() in CENTROID_KEYS:
                return point_from_centroid_value(mapping["value"])
            return None
        return point_from_lon_lat(
            value_from_aliases(mapping, ("longitude", "lon", "lng", "x")),
            value_from_aliases(mapping, ("latitude", "lat", "y")),
        )

    key_value_mapping = key_value_list_to_mapping(value)
    if key_value_mapping:
        return point_from_centroid_value(key_value_mapping)

    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return point_from_lon_lat(value[0], value[1])

    if isinstance(value, str):
        parts = [part.strip() for part in value.replace(";", ",").split(",")]
        if len(parts) == 1:
            parts = value.split()
        if len(parts) >= 2:
            return point_from_lon_lat(parts[0], parts[1])

    return None


def centroid_from_mapping(
    mapping: dict[str, Any], source: str
) -> tuple[Point, str] | None:
    normalized = normalize_mapping_keys(mapping)

    for centroid_key in CENTROID_KEYS:
        if centroid_key in normalized:
            point = point_from_centroid_value(normalized[centroid_key])
            if point is not None:
                return point, f"{source}.{centroid_key}"

    point = point_from_lon_lat(
        value_from_aliases(
            normalized,
            ("centroid_longitude", "centroid_lon", "longitude", "lon", "lng", "x"),
        ),
        value_from_aliases(
            normalized, ("centroid_latitude", "centroid_lat", "latitude", "lat", "y")
        ),
    )
    if point is not None:
        return point, f"{source} longitude/latitude keys"

    key_value_mapping = key_value_list_to_mapping(mapping)
    if key_value_mapping:
        return centroid_from_mapping(key_value_mapping, source)

    return None


def centroid_from_key_value_containers(
    summary: dict[str, Any], source: str
) -> tuple[Point, str] | None:
    for key in ("metadata", "properties", "attributes"):
        value = summary.get(key)
        key_value_mapping = key_value_list_to_mapping(value)
        if not key_value_mapping:
            continue

        centroid = centroid_from_mapping(key_value_mapping, f"{source}.{key}")
        if centroid is not None:
            return centroid

        nested = value_from_aliases(key_value_mapping, CENTROID_KEYS)
        point = point_from_centroid_value(nested)
        if point is not None:
            return point, f"{source}.{key}.centroid"

    return None


def extract_multipolygon_wkt(summary: dict[str, Any]) -> str:
    collection = summary.get("collection")
    if isinstance(collection, dict):
        value = collection.get("multipolygon_wkt")
        if isinstance(value, str) and value:
            return value

    value = summary.get("multipolygon_wkt")
    if isinstance(value, str) and value:
        return value

    raise ValueError("Could not find collection.multipolygon_wkt in collection summary JSON")


def extract_centroid(
    summary: dict[str, Any], pointcloud_path: str | Path | None = None
) -> tuple[Point, str]:
    for value, source in ((summary.get("collection"), "collection"), (summary, "root")):
        if not isinstance(value, dict):
            continue

        direct = centroid_from_mapping(value, source)
        if direct is not None:
            return direct

        from_container = centroid_from_key_value_containers(value, source)
        if from_container is not None:
            return from_container

    try:
        multipolygon_wkt = extract_multipolygon_wkt(summary)
    except ValueError:
        if pointcloud_path:
            return pointcloud_centroid_from_header(pointcloud_path)
        raise ValueError(
            "Could not find a centroid or collection.multipolygon_wkt in the "
            "collection summary JSON. Pass --pointcloud to derive the centroid "
            "from LAS/LAZ header bounds."
        )

    return centroid_from_wkt(multipolygon_wkt), "shapely.centroid(collection.multipolygon_wkt)"


def centroid_from_wkt(multipolygon_wkt: str) -> Point:
    geometry = wkt.loads(multipolygon_wkt)
    if geometry.is_empty:
        raise ValueError("collection.multipolygon_wkt is an empty geometry")
    centroid = geometry.centroid
    if centroid.is_empty:
        raise ValueError("Could not compute centroid from collection.multipolygon_wkt")
    return centroid


def validate_finite_point(point: Point, source: str) -> None:
    if not math.isfinite(point.x) or not math.isfinite(point.y):
        raise ValueError(f"{source} produced a non-finite centroid")


def pointcloud_centroid_from_header(pointcloud_path: str | Path) -> tuple[Point, str]:
    path = Path(pointcloud_path)
    with laspy.open(path) as reader:
        header = reader.header
        if header.point_count <= 0:
            raise ValueError(f"Point cloud contains no points: {path}")

        center_x = (float(header.mins[0]) + float(header.maxs[0])) / 2
        center_y = (float(header.mins[1]) + float(header.maxs[1])) / 2
        point = Point(center_x, center_y)
        validate_finite_point(point, "pointcloud header bounds")

        source_crs = header.parse_crs()

    if source_crs is None:
        if -180 <= point.x <= 180 and -90 <= point.y <= 90:
            return point, "pointcloud.header.bounds"
        raise ValueError(
            "Point cloud header does not contain a CRS, and header bounds do not "
            "look like WGS84 longitude/latitude coordinates."
        )

    crs = CRS.from_user_input(source_crs)
    wgs84 = CRS.from_epsg(4326)
    if crs != wgs84:
        transformer = Transformer.from_crs(crs, wgs84, always_xy=True)
        point = transform(transformer.transform, point)
        validate_finite_point(point, "transformed pointcloud header bounds")

    return point, "pointcloud.header.bounds"


def list_layers(vector_path: str, layer_name: str) -> list[str | None]:
    if layer_name:
        return [layer_name]

    layers = list(fiona.listlayers(vector_path))
    if layers:
        return layers

    # Shapefiles can be opened without a layer name.
    return [None]


def infer_admin_level(fields: list[str]) -> int | None:
    levels: list[int] = []
    for level in range(6):
        if f"GID_{level}" in fields or f"NAME_{level}" in fields:
            levels.append(level)

    if "COUNTRY" in fields and 0 not in levels:
        levels.append(0)

    return max(levels) if levels else None


def has_raw_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def infer_populated_admin_level(raw_fields: dict[str, Any]) -> int | None:
    levels: list[int] = []
    for level in range(6):
        if level == 0:
            level_items = (
                (key, value)
                for key, value in raw_fields.items()
                if key.endswith("_0") or key in {"COUNTRY", "CONTINENT", "SUBCONT"}
            )
        else:
            level_items = (
                (key, value)
                for key, value in raw_fields.items()
                if key.endswith(f"_{level}")
            )

        if any(has_raw_value(value) for _, value in level_items):
            levels.append(level)

    return max(levels) if levels else None


def build_gadm_levels(raw_fields: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(level): {
            field_name: raw_fields.get(field_name)
            for field_name in field_names
        }
        for level, field_names in GADM_LEVEL_FIELDS.items()
    }


def build_null_gadm_raw_fields() -> dict[str, Any]:
    raw_fields: dict[str, Any] = {}
    for field_names in GADM_LEVEL_FIELDS.values():
        for field_name in field_names:
            raw_fields[field_name] = None
    return raw_fields


def normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, (int, float, bool)):
        return value
    return str(value)


def normalize_properties(properties: Any) -> dict[str, Any]:
    return {
        str(key): normalize_value(value)
        for key, value in dict(properties).items()
    }


def collection_crs(collection: fiona.Collection) -> CRS | None:
    if collection.crs_wkt:
        return CRS.from_wkt(collection.crs_wkt)
    if collection.crs:
        return CRS.from_user_input(collection.crs)
    return None


def point_for_layer(point_wgs84: Point, layer_crs: CRS | None) -> Point:
    if layer_crs is None:
        return point_wgs84

    wgs84 = CRS.from_epsg(4326)
    if layer_crs == wgs84:
        return point_wgs84

    transformer = Transformer.from_crs(wgs84, layer_crs, always_xy=True)
    return transform(transformer.transform, point_wgs84)


def open_layer(vector_path: str, layer_name: str | None) -> fiona.Collection:
    if layer_name is None:
        return fiona.open(vector_path)
    return fiona.open(vector_path, layer=layer_name)


def features_near_point(collection: fiona.Collection, point: Point) -> Any:
    epsilon = 1e-9
    bbox = (
        point.x - epsilon,
        point.y - epsilon,
        point.x + epsilon,
        point.y + epsilon,
    )
    try:
        return collection.filter(bbox=bbox)
    except Exception:
        return collection


def match_layer(
    vector_path: str,
    layer_name: str | None,
    point_wgs84: Point,
    level_fn: Callable[[list[str]], int | None] = infer_admin_level,
    matched_level_fn: Callable[[dict[str, Any]], int | None] | None = None,
) -> dict[str, Any]:
    display_layer = layer_name or Path(vector_path).stem

    with open_layer(vector_path, layer_name) as collection:
        fields = list(collection.schema.get("properties", {}).keys())
        layer_level = level_fn(fields)
        layer_point = point_for_layer(point_wgs84, collection_crs(collection))
        hits: list[dict[str, Any]] = []

        for feature in features_near_point(collection, layer_point):
            geometry = feature.get("geometry")
            if not geometry:
                continue
            feature_geometry = shape(geometry)
            if feature_geometry.intersects(layer_point):
                hits.append(normalize_properties(feature.get("properties", {})))

    if not hits:
        return {
            "layer": display_layer,
            "matched": False,
            "level": layer_level,
        }

    raw_fields = hits[0]
    match = {
        "layer": display_layer,
        "matched": True,
        "level": matched_level_fn(raw_fields)
        if matched_level_fn is not None
        else level_fn(list(raw_fields.keys())),
        "match_count": len(hits),
        "raw_fields": raw_fields,
    }
    return match


def infer_ecoregion_level(fields: list[str]) -> int | None:
    normalized = {field.upper() for field in fields}
    return (
        0
        if "ECO_NAME" in normalized or "ECO_ID" in normalized or "BIOME" in normalized
        else None
    )


def select_best_match(layer_matches: list[dict[str, Any]]) -> dict[str, Any] | None:
    matched = [match for match in layer_matches if match.get("matched") is True]
    if not matched:
        return None

    return max(
        matched,
        key=lambda match: match.get("level") if match.get("level") is not None else -1,
    )


def build_result(
    args: argparse.Namespace,
    centroid: Point,
    centroid_method: str,
    gadm_layers: list[str | None],
    gadm_layer_matches: list[dict[str, Any]],
    wwf_layers: list[str | None] | None = None,
    wwf_layer_matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "lookup": {
            "centroid": {
                "longitude": centroid.x,
                "latitude": centroid.y,
                "crs": "EPSG:4326",
                "method": centroid_method,
            },
            "reference_layers_checked": [],
        }
    }

    if args.gadm_path:
        layer_names = [layer or Path(args.gadm_path).stem for layer in gadm_layers]
        result["lookup"]["reference_layers_checked"].append(
            {
                "metadata_layer": "gadm",
                "dataset": "GADM",
                "path": Path(args.gadm_path).name,
                "layers_checked": layer_names,
            }
        )
        best_match = select_best_match(gadm_layer_matches)
        warnings: list[str] = []

        base_admin: dict[str, Any] = {}

        if best_match is None:
            warnings.append("Centroid did not intersect any GADM feature")
            raw_fields = build_null_gadm_raw_fields()
            base_admin.update(
                {
                    "matched": False,
                    "selected_layer": None,
                    "match_count": 0,
                    "raw_fields": raw_fields,
                    "levels": build_gadm_levels(raw_fields),
                    "warnings": warnings,
                }
            )
        else:
            match_count = best_match.get("match_count")
            if isinstance(match_count, int) and match_count > 1:
                warnings.append(
                    f"Selected layer intersects {match_count} GADM features; first feature was used"
                )

            base_admin.update(
                {
                    "matched": True,
                    "selected_layer": best_match.get("layer"),
                    "match_count": match_count,
                    "raw_fields": best_match.get("raw_fields", {}),
                    "levels": build_gadm_levels(best_match.get("raw_fields", {})),
                    "warnings": warnings,
                }
            )

        result["admin"] = base_admin

    if args.wwf_ecoregions_path:
        layer_names = [
            layer or Path(args.wwf_ecoregions_path).stem for layer in (wwf_layers or [])
        ]
        result["lookup"]["reference_layers_checked"].append(
            {
                "metadata_layer": "ecoregion",
                "dataset": "WWF Terrestrial Ecoregions v2.0",
                "path": Path(args.wwf_ecoregions_path).name,
                "layers_checked": layer_names,
            }
        )
        result["ecoregion"] = build_ecoregion_result(
            layer_matches=wwf_layer_matches or [],
        )

    return result


def build_ecoregion_result(layer_matches: list[dict[str, Any]]) -> dict[str, Any]:
    best_match = select_best_match(layer_matches)
    warnings: list[str] = []

    ecoregion: dict[str, Any] = {}

    if best_match is None:
        warnings.append("Centroid did not intersect any WWF ecoregion feature")
        ecoregion.update(
            {
                "matched": False,
                "warnings": warnings,
            }
        )
        return ecoregion

    match_count = best_match.get("match_count")
    if isinstance(match_count, int) and match_count > 1:
        warnings.append(
            f"Selected layer intersects {match_count} WWF features; first feature was used"
        )

    ecoregion.update(
        {
            "matched": True,
            "selected_layer": best_match.get("layer"),
            "match_count": match_count,
            "raw_fields": best_match.get("raw_fields", {}),
            "warnings": warnings,
        }
    )
    return ecoregion


def main() -> None:
    args = parse_args()
    summary = read_json(args.collection_summary)
    centroid, centroid_method = extract_centroid(summary, args.pointcloud or None)

    print(f"Using centroid lon={centroid.x} lat={centroid.y} ({centroid_method})")

    gadm_layers: list[str | None] = []
    gadm_layer_matches = []
    if "gadm" in args.metadata_layers:
        args.gadm_path = resolve_reference_dataset(args, "gadm")
        gadm_layers = list_layers(args.gadm_path, args.gadm_layer)
        print(f"Checking {len(gadm_layers)} GADM layer(s)")
        for layer_name in gadm_layers:
            print(f"Reading GADM layer: {layer_name or Path(args.gadm_path).stem}")
            gadm_layer_matches.append(
                match_layer(
                    args.gadm_path,
                    layer_name,
                    centroid,
                    matched_level_fn=infer_populated_admin_level,
                )
            )

    wwf_layers = None
    wwf_layer_matches = None
    if "ecoregion" in args.metadata_layers:
        args.wwf_ecoregions_path = resolve_reference_dataset(args, "ecoregion")
        wwf_layers = list_layers(args.wwf_ecoregions_path, args.wwf_ecoregions_layer)
        print(f"Checking {len(wwf_layers)} WWF ecoregions layer(s)")
        wwf_layer_matches = []
        for layer_name in wwf_layers:
            print(
                "Reading WWF ecoregions layer: "
                f"{layer_name or Path(args.wwf_ecoregions_path).stem}"
            )
            wwf_layer_matches.append(
                match_layer(
                    args.wwf_ecoregions_path,
                    layer_name,
                    centroid,
                    level_fn=infer_ecoregion_level,
                )
            )

    result = build_result(
        args,
        centroid,
        centroid_method,
        gadm_layers,
        gadm_layer_matches,
        wwf_layers=wwf_layers,
        wwf_layer_matches=wwf_layer_matches,
    )
    with Path(args.output_file).open("w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")

    print(f"Wrote metadata to: {args.output_file}")


if __name__ == "__main__":
    main()

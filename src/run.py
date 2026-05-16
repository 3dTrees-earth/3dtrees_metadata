#!/usr/bin/env python3
"""Extract administrative and ecoregion metadata for a 3Dtrees collection summary."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlretrieve
import zipfile

import fiona
from pyproj import CRS, Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform
from shapely import wkt


SUPPORTED_METADATA_LAYERS = ("gadm", "ecoregion")
DEFAULT_REFERENCE_DATA_DIR = "/reference-data"
DEFAULT_GADM_URL = "https://geodata.ucdavis.edu/gadm/gadm4.1/gadm_410-gpkg.zip"
DEFAULT_WWF_ECOREGIONS_URL = (
    "https://files.worldwildlife.org/wwfcmsprod/files/Publication/file/"
    "6kcchn7e3u_official_teow.zip"
)

REFERENCE_DATASETS = {
    "gadm": {
        "download_arg": "gadm_url",
        "path_arg": "gadm_path",
        "preferred_names": ("gadm_410.gpkg", "gadm.gpkg", "gadm_fixture.geojson"),
        "extensions": (".gpkg", ".geojson", ".shp"),
    },
    "ecoregion": {
        "download_arg": "wwf_ecoregions_url",
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
        "--reference-data-dir",
        "--reference_data_dir",
        dest="reference_data_dir",
        default=os.environ.get(
            "THREEDTREES_METADATA_REFERENCE_DIR", DEFAULT_REFERENCE_DATA_DIR
        ),
        help=(
            "Directory used for cached reference datasets. Missing datasets are "
            "downloaded into this directory."
        ),
    )
    parser.add_argument(
        "--download-missing-reference-data",
        action="store_true",
        help=(
            "Download missing reference datasets into --reference-data-dir. "
            "By default the tool expects reference data to be present in the Docker image."
        ),
    )
    parser.add_argument(
        "--gadm-url",
        "--gadm_url",
        dest="gadm_url",
        default=os.environ.get("THREEDTREES_GADM_URL", DEFAULT_GADM_URL),
        help="Download URL for the GADM reference dataset.",
    )
    parser.add_argument(
        "--wwf-ecoregions-url",
        "--wwf_ecoregions_url",
        "--wwf-url",
        "--wwf_url",
        dest="wwf_ecoregions_url",
        default=os.environ.get(
            "THREEDTREES_WWF_ECOREGIONS_URL", DEFAULT_WWF_ECOREGIONS_URL
        ),
        help="Download URL for the WWF Terrestrial Ecoregions v2.0 dataset.",
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


def download_reference_archive(url: str, download_path: Path) -> Path:
    download_path.parent.mkdir(parents=True, exist_ok=True)

    parsed_url = urlparse(url)
    if parsed_url.scheme in ("", "file"):
        source_path = Path(parsed_url.path if parsed_url.scheme == "file" else url)
        if not source_path.exists():
            raise FileNotFoundError(f"Reference dataset source does not exist: {url}")
        shutil.copyfile(source_path, download_path)
        return download_path

    print(f"Downloading reference dataset: {url}")
    urlretrieve(url, download_path)
    return download_path


def unpack_reference_archive(archive_path: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(target_dir)
        return

    raise ValueError(f"Unsupported reference dataset archive: {archive_path}")


def resolve_reference_dataset(args: argparse.Namespace, layer: str) -> str:
    config = REFERENCE_DATASETS[layer]
    explicit_path = getattr(args, str(config["path_arg"]))
    if explicit_path:
        path = Path(explicit_path)
        if not path.exists():
            raise FileNotFoundError(f"{layer} reference path does not exist: {path}")
        return str(path)

    layer_dir = reference_data_dir(args, layer)
    reference_file = find_reference_file(
        layer_dir,
        config["preferred_names"],  # type: ignore[arg-type]
        config["extensions"],  # type: ignore[arg-type]
    )
    if reference_file is not None:
        return str(reference_file)

    if not args.download_missing_reference_data:
        raise FileNotFoundError(
            f"Could not find a usable {layer} vector dataset in {layer_dir}. "
            "Add the reference data to the Docker image under /reference-data "
            "or rerun with --download-missing-reference-data."
        )

    url = getattr(args, str(config["download_arg"]))
    archive_name = Path(urlparse(url).path).name or f"{layer}.zip"
    archive_path = layer_dir / "downloads" / archive_name
    download_reference_archive(url, archive_path)
    unpack_reference_archive(archive_path, layer_dir)

    reference_file = find_reference_file(
        layer_dir,
        config["preferred_names"],  # type: ignore[arg-type]
        config["extensions"],  # type: ignore[arg-type]
    )
    if reference_file is None:
        raise FileNotFoundError(
            f"Could not find a usable {layer} vector dataset in {layer_dir}"
        )

    return str(reference_file)


def read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


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


def centroid_from_wkt(multipolygon_wkt: str) -> Point:
    geometry = wkt.loads(multipolygon_wkt)
    if geometry.is_empty:
        raise ValueError("collection.multipolygon_wkt is an empty geometry")
    centroid = geometry.centroid
    if centroid.is_empty:
        raise ValueError("Could not compute centroid from collection.multipolygon_wkt")
    return centroid


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


def normalize_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def normalize_properties(properties: Any) -> dict[str, Any]:
    return {
        str(key): normalize_value(value)
        for key, value in dict(properties).items()
        if value is not None
    }


def build_admin_levels(raw_fields: dict[str, Any]) -> list[dict[str, Any]]:
    admin_levels: list[dict[str, Any]] = []

    for level in range(6):
        gid_key = f"GID_{level}"
        name_key = "COUNTRY" if level == 0 else f"NAME_{level}"
        type_key = f"TYPE_{level}"
        engtype_key = f"ENGTYPE_{level}"

        gid = raw_fields.get(gid_key)
        name = raw_fields.get(name_key)
        if name is None and level == 0:
            name = raw_fields.get("NAME_0")

        if gid is None and name is None:
            continue

        entry: dict[str, Any] = {
            "level": level,
            "gid": gid,
            "name": name,
        }
        if raw_fields.get(type_key) is not None:
            entry["type"] = raw_fields[type_key]
        if raw_fields.get(engtype_key) is not None:
            entry["engtype"] = raw_fields[engtype_key]

        admin_levels.append(entry)

    return admin_levels


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


def match_layer(
    vector_path: str,
    layer_name: str | None,
    point_wgs84: Point,
    level_fn=infer_admin_level,
    include_admin_levels: bool = True,
) -> dict[str, Any]:
    display_layer = layer_name or Path(vector_path).stem

    with open_layer(vector_path, layer_name) as collection:
        fields = list(collection.schema.get("properties", {}).keys())
        layer_level = level_fn(fields)
        layer_point = point_for_layer(point_wgs84, collection_crs(collection))
        hits: list[dict[str, Any]] = []

        for feature in collection:
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
        "level": level_fn(list(raw_fields.keys())),
        "match_count": len(hits),
        "raw_fields": raw_fields,
    }
    if include_admin_levels:
        match["admin_levels"] = build_admin_levels(raw_fields)
    return match


WWF_BIOME_NAMES = {
    1: "Tropical & Subtropical Moist Broadleaf Forests",
    2: "Tropical & Subtropical Dry Broadleaf Forests",
    3: "Tropical & Subtropical Coniferous Forests",
    4: "Temperate Broadleaf & Mixed Forests",
    5: "Temperate Conifer Forests",
    6: "Boreal Forests/Taiga",
    7: "Tropical & Subtropical Grasslands, Savannas & Shrublands",
    8: "Temperate Grasslands, Savannas & Shrublands",
    9: "Flooded Grasslands & Savannas",
    10: "Montane Grasslands & Shrublands",
    11: "Tundra",
    12: "Mediterranean Forests, Woodlands & Scrub",
    13: "Deserts & Xeric Shrublands",
    14: "Mangroves",
}

FOREST_BIOME_CODES = {1, 2, 3, 4, 5, 6, 12, 14}


def infer_ecoregion_level(fields: list[str]) -> int | None:
    normalized = {field.upper() for field in fields}
    return (
        0
        if "ECO_NAME" in normalized or "ECO_ID" in normalized or "BIOME" in normalized
        else None
    )


def first_present(raw_fields: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = raw_fields.get(key)
        if value is not None and value != "":
            return value
        for raw_key, raw_value in raw_fields.items():
            if raw_key.upper() == key.upper() and raw_value is not None and raw_value != "":
                return raw_value
    return None


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def build_ecoregion_summary(best_match: dict[str, Any]) -> dict[str, Any]:
    raw_fields = best_match.get("raw_fields", {})
    biome_code = as_int(first_present(raw_fields, ["BIOME", "BIOME_NUM", "BIOME_ID"]))
    biome_name = first_present(raw_fields, ["BIOME_NAME", "BIOME_DESC"])
    if biome_name is None and biome_code is not None:
        biome_name = WWF_BIOME_NAMES.get(biome_code)

    ecoregion_id = first_present(raw_fields, ["ECO_ID", "ECO_NUM", "ECO_CODE"])

    return {
        "ecoregion_name": first_present(raw_fields, ["ECO_NAME", "ECOREGION"]),
        "ecoregion_id": ecoregion_id,
        "realm": first_present(raw_fields, ["REALM"]),
        "biome_code": biome_code,
        "biome_name": biome_name,
        "is_forest_biome": biome_code in FOREST_BIOME_CODES
        if biome_code is not None
        else None,
    }


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
    gadm_layers: list[str | None],
    gadm_layer_matches: list[dict[str, Any]],
    wwf_layers: list[str | None] | None = None,
    wwf_layer_matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}

    if args.gadm_path:
        layer_names = [layer or Path(args.gadm_path).stem for layer in gadm_layers]
        best_match = select_best_match(gadm_layer_matches)
        warnings: list[str] = []

        base_admin: dict[str, Any] = {
            "source": {
                "dataset": "GADM",
                "path": Path(args.gadm_path).name,
                "layers_checked": layer_names,
            },
            "centroid": {
                "longitude": centroid.x,
                "latitude": centroid.y,
                "crs": "EPSG:4326",
                "method": "shapely.centroid(collection.multipolygon_wkt)",
            },
            "matches_by_layer": gadm_layer_matches,
        }

        if best_match is None:
            warnings.append("Centroid did not intersect any GADM feature")
            base_admin.update(
                {
                    "matched": False,
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
                    "selected_level": best_match.get("level"),
                    "admin_levels": best_match.get("admin_levels", []),
                    "raw_fields": best_match.get("raw_fields", {}),
                    "warnings": warnings,
                }
            )

        result["admin"] = base_admin

    if args.wwf_ecoregions_path:
        result["ecoregion"] = build_ecoregion_result(
            args=args,
            centroid=centroid,
            layers=wwf_layers or [],
            layer_matches=wwf_layer_matches or [],
        )

    return result


def build_ecoregion_result(
    args: argparse.Namespace,
    centroid: Point,
    layers: list[str | None],
    layer_matches: list[dict[str, Any]],
) -> dict[str, Any]:
    layer_names = [layer or Path(args.wwf_ecoregions_path).stem for layer in layers]
    best_match = select_best_match(layer_matches)
    warnings: list[str] = []

    ecoregion: dict[str, Any] = {
        "source": {
            "dataset": "WWF Terrestrial Ecoregions v2.0",
            "path": Path(args.wwf_ecoregions_path).name,
            "layers_checked": layer_names,
        },
        "centroid": {
            "longitude": centroid.x,
            "latitude": centroid.y,
            "crs": "EPSG:4326",
            "method": "shapely.centroid(collection.multipolygon_wkt)",
        },
        "matches_by_layer": layer_matches,
    }

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
            **build_ecoregion_summary(best_match),
            "raw_fields": best_match.get("raw_fields", {}),
            "warnings": warnings,
        }
    )
    return ecoregion


def main() -> None:
    args = parse_args()
    summary = read_json(args.collection_summary)
    multipolygon_wkt = extract_multipolygon_wkt(summary)
    centroid = centroid_from_wkt(multipolygon_wkt)

    print(f"Using centroid lon={centroid.x} lat={centroid.y}")

    gadm_layers: list[str | None] = []
    gadm_layer_matches = []
    if "gadm" in args.metadata_layers:
        args.gadm_path = resolve_reference_dataset(args, "gadm")
        gadm_layers = list_layers(args.gadm_path, args.gadm_layer)
        print(f"Checking {len(gadm_layers)} GADM layer(s)")
        for layer_name in gadm_layers:
            print(f"Reading GADM layer: {layer_name or Path(args.gadm_path).stem}")
            gadm_layer_matches.append(match_layer(args.gadm_path, layer_name, centroid))

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
                    include_admin_levels=False,
                )
            )

    result = build_result(
        args,
        centroid,
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

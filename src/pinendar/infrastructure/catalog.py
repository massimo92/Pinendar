import json
import unicodedata
from pathlib import Path
from typing import Any


def normalized(value: str) -> str:
    text = unicodedata.normalize("NFD", value)
    return " ".join("".join(char for char in text if unicodedata.category(char) != "Mn").lower().split())


class HospitalCatalog:
    def __init__(self, directory: Path):
        catalog_file = directory / "catalog.json"
        areas_file = directory / "areas.json"
        raw = json.loads(catalog_file.read_text()) if catalog_file.exists() else {"metadata": {}, "hospitals": []}
        areas = json.loads(areas_file.read_text()).get("areas", {}) if areas_file.exists() else {}
        self.metadata: dict[str, Any] = raw.get("metadata", {})
        self.hospitals: list[dict[str, Any]] = raw.get("hospitals", [])
        self.by_id = {item["id"]: item for item in self.hospitals}
        self.areas: dict[str, Any] = areas

    def details(self, catalog_id: str) -> dict[str, Any] | None:
        hospital = self.by_id.get(catalog_id)
        return {**hospital, "geometry": self.areas.get(catalog_id)} if hospital else None

    def search(self, query: str) -> dict[str, Any]:
        needle = normalized(query)
        if len(needle) < 2:
            return {"items": [], "total": 0, "catalog": self.metadata}
        terms = needle.split()
        matches = []
        for item in self.hospitals:
            haystack = normalized(
                " ".join(
                    str(item.get(key, ""))
                    for key in ("name", "municipality", "province", "region", "streetAddress", "postcode", "cnhCode")
                )
            )
            if all(term in haystack for term in terms):
                name = normalized(item.get("name", ""))
                municipality = normalized(item.get("municipality", ""))
                score = (
                    1000
                    if name == needle
                    else 700
                    if name.startswith(needle)
                    else 600
                    if municipality == needle
                    else 450
                    if municipality.startswith(needle)
                    else 0
                )
                matches.append((score - max(0, haystack.find(needle)), item))
        matches.sort(key=lambda match: (-match[0], match[1].get("name", "")))
        return {"items": [item for _, item in matches[:18]], "total": len(matches), "catalog": self.metadata}

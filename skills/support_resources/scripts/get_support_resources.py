"""
Deterministic implementation backing the `get_support_resources` tool.

Per the Agent Skills pattern: "the model decides what to do; the script does the heavy
lifting." The model only ever sees the small tool *declaration* (see SUPPORT_RESOURCES_TOOL in
app.py) and the final JSON result of calling get_support_resources(country) — never the raw
reference data file directly, and never this code.

The reference data lives in references/resources_by_country.json and is loaded lazily (on the
first actual tool call), not at import time, so it never inflates app.py's always-resident
memory/context footprint.
"""
import json
import os

_REFERENCES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references",
    "resources_by_country.json",
)

# Common country name variants -> canonical key in resources_by_country.json
COUNTRY_MAP = {
    # English names
    "argentina": "argentina",
    "united states": "united states", "usa": "united states", "us": "united states", "america": "united states",
    "united kingdom": "united kingdom", "uk": "united kingdom", "england": "united kingdom", "britain": "united kingdom",
    "canada": "canada",
    "australia": "australia",
    "mexico": "mexico", "méxico": "mexico",
    "spain": "spain", "españa": "spain",
    "brazil": "brazil", "brasil": "brazil",
    # Spanish names
    "estados unidos": "united states",
    "reino unido": "united kingdom",
    "canadá": "canada",
}

_db_cache = None


def load_resources_db(path: str = _REFERENCES_PATH) -> dict:
    """
    Lazily loads and caches the country -> resources reference data from disk.
    Cached at module level so repeated tool calls in the same process don't re-read the file,
    while still keeping the data out of app.py's source/import-time memory footprint.
    """
    global _db_cache
    if _db_cache is None:
        with open(path, "r", encoding="utf-8") as f:
            _db_cache = json.load(f)
    return _db_cache


def get_support_resources(country: str, path: str = _REFERENCES_PATH) -> dict:
    """
    Tool implementation: returns verified support resources for the given country.
    Maps common country name variants to the canonical database key.
    """
    db = load_resources_db(path)
    key = COUNTRY_MAP.get(country.lower().strip(), "default")
    return db.get(key, db["default"])


def format_resources_as_markdown(resources_data: dict) -> str:
    """
    Formats a get_support_resources() result into a clean markdown block for the chat UI.
    """
    flag = resources_data.get("flag", "🌍")
    country = resources_data.get("country", "your country")
    resources = resources_data.get("resources", [])

    lines = [f"\n\n---\n### {flag} Support Resources for {country}\n"]
    for r in resources:
        lines.append(f"**{r['name']}**")
        lines.append(f"- 📞 Contact: `{r['contact']}`")
        lines.append(f"- 🏷️ Type: {r['type']}")
        if r.get("notes"):
            lines.append(f"- ℹ️ {r['notes']}")
        lines.append("")
    lines.append(
        "---\n*These resources are curated and verified. If your country isn't listed, visit "
        "[UNICEF's country resources](https://www.unicef.org) or search for your national child "
        "protection hotline.*"
    )
    return "\n".join(lines)


if __name__ == "__main__":
    # Quick manual check: `python get_support_resources.py Argentina`
    import sys
    country_arg = sys.argv[1] if len(sys.argv) > 1 else "default"
    data = get_support_resources(country_arg)
    print(format_resources_as_markdown(data))

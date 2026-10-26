"""Partes comunes de los paquetes Office Open XML (DOCX, XLSX)."""

import zipfile
from pathlib import Path

from lxml import etree

_CUSTOM_PROPS_NS = {
    "cp": "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties",
}
_SAFE_XML_PARSER = etree.XMLParser(resolve_entities=False, no_network=True)


def custom_properties(path: Path) -> dict[str, str]:
    """Propiedades de ``docProps/custom.xml`` (p. ej. ``Referencia``), que las librerías no leen."""
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("docProps/custom.xml")
    except (KeyError, zipfile.BadZipFile):
        return {}
    root = etree.fromstring(xml, parser=_SAFE_XML_PARSER)
    properties = {}
    for prop in root.findall("cp:property", _CUSTOM_PROPS_NS):
        values = [child.text for child in prop if child.text]
        if prop.get("name") and values:
            properties[prop.get("name")] = values[0].strip()
    return properties

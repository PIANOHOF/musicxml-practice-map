#!/usr/bin/env python3
"""Inventory written MusicXML indications, without inferring musical time."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sys
import xml.etree.ElementTree as ET
from xml.parsers import expat
import zipfile

VERSION = "1.0.0"
MAX_INPUT = 16 * 1024 * 1024
MAX_XML = 8 * 1024 * 1024
MAX_ARCHIVE_TOTAL = 32 * 1024 * 1024
MAX_MEMBERS = 256
MAX_ELEMENTS = 100_000
MAX_DEPTH = 128
MAX_RATIO = 200
XML_MEDIA = "application/vnd.recordare.musicxml+xml"
ATTRIBUTE_TAGS = {
    "divisions", "key", "time", "staves", "clef", "transpose",
    "for-part", "staff-details", "measure-style", "instruments", "part-symbol",
}


class ScoreError(ValueError):
    """A bounded or unsupported input, reported without a traceback by the CLI."""


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element if local_name(child.tag) == name]


def child_text(element: ET.Element, name: str) -> str | None:
    found = children(element, name)
    return " ".join("".join(found[0].itertext()).split()) if found else None


def checked_xml(data: bytes) -> ET.Element:
    """Bound parsing before building a tree. Never load an external DTD/entity."""
    if sys.version_info < (3, 12) or expat.version_info < (2, 6, 0):
        raise ScoreError("Use Python 3.12+ with Expat 2.6.0+; update the local runtime.")
    if not data or len(data) > MAX_XML:
        raise ScoreError("XML is empty or exceeds the 8 MiB limit.")
    parser = expat.ParserCreate()
    depth = count = 0

    def start(_name, _attributes):
        nonlocal depth, count
        depth += 1
        count += 1
        if depth > MAX_DEPTH or count > MAX_ELEMENTS:
            raise ScoreError("XML exceeds the element/depth limit.")

    def end(_name):
        nonlocal depth
        depth -= 1

    def declaration(_name, _system, _public, internal):
        if internal:
            raise ScoreError("Internal DTD subsets are not supported.")

    def entity(*_args):
        raise ScoreError("Entity declarations/references are not supported.")

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.StartDoctypeDeclHandler = declaration
    parser.EntityDeclHandler = entity
    parser.ExternalEntityRefHandler = entity
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(data, True)
        return ET.fromstring(data)
    except (expat.ExpatError, ET.ParseError, LookupError) as error:
        raise ScoreError(f"Malformed XML: {error}") from error


def archive_path(name: str) -> str:
    path = PurePosixPath(name)
    if (not name or "\\" in name or "\x00" in name or path.is_absolute()
            or ":" in name or any(piece in ("", ".", "..") for piece in name.split("/"))):
        raise ScoreError("MXL root path must be a normal relative archive path.")
    return name


def unwrap(data: bytes, is_mxl: bool) -> tuple[ET.Element, str | None]:
    if not is_mxl:
        return checked_xml(data), None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(infos) > MAX_MEMBERS or len(names) != len(set(names)):
                raise ScoreError("MXL has too many members or duplicate member names.")
            if sum(item.file_size for item in infos) > MAX_ARCHIVE_TOTAL:
                raise ScoreError("MXL declared uncompressed contents exceed 32 MiB.")
            if any(item.flag_bits & 1 for item in infos):
                raise ScoreError("Encrypted MXL members are not supported.")

            def read_member(name: str) -> bytes:
                try:
                    info = archive.getinfo(name)
                except KeyError as error:
                    raise ScoreError(f"Missing MXL member: {name}") from error
                if info.is_dir() or info.file_size > MAX_XML:
                    raise ScoreError("Selected MXL XML member is a directory or exceeds 8 MiB.")
                if info.file_size > max(info.compress_size, 1) * MAX_RATIO:
                    raise ScoreError("Selected MXL XML member exceeds the expansion-ratio limit.")
                with archive.open(info) as stream:
                    result = stream.read(MAX_XML + 1)
                if len(result) > MAX_XML:
                    raise ScoreError("Selected MXL XML member exceeds 8 MiB.")
                return result

            manifest = checked_xml(read_member("META-INF/container.xml"))
            if local_name(manifest.tag) != "container":
                raise ScoreError("MXL manifest must have a container root.")
            rootfiles = children(manifest, "rootfiles")
            if len(rootfiles) != 1:
                raise ScoreError("MXL requires one rootfiles element.")
            roots = children(rootfiles[0], "rootfile")
            if not roots:
                raise ScoreError("MXL declares no rootfile.")
            # MusicXML defines the first rootfile as the MusicXML root, not the
            # first XML ZIP member or the first member with a familiar suffix.
            first = roots[0]
            if first.get("media-type") not in (None, XML_MEDIA):
                raise ScoreError("The first declared MXL rootfile is not MusicXML.")
            selected = archive_path(first.get("full-path", ""))
            return checked_xml(read_member(selected)), selected
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError) as error:
        raise ScoreError(f"Unreadable or unsupported MXL container: {error}") from error


def written(element: ET.Element) -> dict:
    """Preserve written child/attribute order; do not interpret or inherit it."""
    result = {"element": local_name(element.tag)}
    if element.attrib:
        result["attributes"] = dict(element.attrib)
    text = " ".join((element.text or "").split())
    if text:
        result["text"] = text
    if len(element):
        result["children"] = [written(child) for child in element]
    return result


def measure_map(measure: ET.Element, index: int) -> dict:
    if "number" not in measure.attrib:
        raise ScoreError("A measure is missing its written number attribute.")
    result = {
        "index": index, "label": measure.get("number"),
        "attributes": dict(measure.attrib), "note_elements": 0,
        "rests": 0, "chord_followers": 0, "grace_note_elements": 0,
        "events": [],
    }
    for position, item in enumerate(measure, 1):
        kind = local_name(item.tag)
        selected = []
        if kind == "note":
            result["note_elements"] += 1
            result["rests"] += bool(children(item, "rest"))
            result["chord_followers"] += bool(children(item, "chord"))
            result["grace_note_elements"] += bool(children(item, "grace"))
        elif kind == "attributes":
            selected = [written(x) for x in item if local_name(x.tag) in ATTRIBUTE_TAGS]
        elif kind == "barline":
            selected = [written(x) for x in item if local_name(x.tag) in {"repeat", "ending"}]
        elif kind == "direction":
            for direction_type in children(item, "direction-type"):
                selected.extend(written(x) for x in children(direction_type, "metronome"))
            for sound in children(item, "sound"):
                if "tempo" in sound.attrib:
                    selected.append(written(sound))
        elif kind == "sound" and "tempo" in item.attrib:
            selected = [written(item)]
        if selected:
            event = {"xml_child_index": position, "container": kind, "written": selected}
            if item.attrib:
                event["container_attributes"] = dict(item.attrib)
            context = [written(x) for x in item if local_name(x.tag) in {"offset", "staff", "voice"}]
            if context:
                event["written_context"] = context
            result["events"].append(event)
    return result


def inspect_score(data: bytes, source_name: str = "score.musicxml") -> dict:
    if len(data) > MAX_INPUT:
        raise ScoreError("Input exceeds the 16 MiB limit.")
    is_mxl = source_name.lower().endswith(".mxl") or data.startswith(b"PK\x03\x04")
    root, member = unwrap(data, is_mxl)
    if local_name(root.tag) != "score-partwise":
        raise ScoreError("Only score-partwise is supported; score-timewise/opus require re-export.")
    lists = children(root, "part-list")
    if len(lists) != 1:
        raise ScoreError("A score-partwise input must contain one part-list.")
    declarations = children(lists[0], "score-part")
    ids = [item.get("id") for item in declarations]
    if not ids or any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ScoreError("Missing or duplicate score-part identifiers.")
    names = {item.get("id"): child_text(item, "part-name") for item in declarations}
    parts = children(root, "part")
    part_ids = [item.get("id") for item in parts]
    if len(part_ids) != len(set(part_ids)) or set(part_ids) != set(ids):
        raise ScoreError("Part identifiers must match the declarations exactly once.")
    report = {
        "tool": "MusicXML Practice Map", "version": VERSION,
        "source_name": Path(source_name).name,
        "input_sha256": hashlib.sha256(data).hexdigest(),
        "container": "mxl" if is_mxl else "xml", "root_member": member,
        "musicxml_version_written": root.get("version"),
        "order": "XML document order; not musical-time or repeat-expanded order",
        "parts": [],
    }
    for part in parts:
        measures = children(part, "measure")
        if not measures:
            raise ScoreError("A part contains no measures.")
        report["parts"].append({
            "id": part.get("id"), "name": names[part.get("id")],
            "measure_count": len(measures),
            "measures": [measure_map(item, i) for i, item in enumerate(measures, 1)],
        })
    return report


def compact(item: dict) -> str:
    label = item["element"]
    if item.get("attributes"):
        label += " " + json.dumps(item["attributes"], ensure_ascii=False, sort_keys=True)
    if "text" in item:
        label += "=" + json.dumps(item["text"], ensure_ascii=False)
    if item.get("children"):
        label += " [" + "; ".join(compact(x) for x in item["children"]) + "]"
    return label


def text_report(report: dict) -> str:
    lines = ["MusicXML Practice Map " + VERSION,
             "Datei: " + json.dumps(report["source_name"], ensure_ascii=False),
             "Reihenfolge: XML-Fundstellen, keine musikalische Zeitachse oder Abspielreihenfolge.",
             "Keine Ton-, Akkord-, Fehler- oder Layoutdiagnose. Fehlende Angaben werden nicht ergänzt."]
    for part in report["parts"]:
        lines.append(f"\nPart {part['id']} ({json.dumps(part['name'], ensure_ascii=False)}): {part['measure_count']} Takteinträge")
        for measure in part["measures"]:
            lines.append(f"  Eintrag {measure['index']}, Beschriftung {json.dumps(measure['label'], ensure_ascii=False)}: "
                         f"{measure['note_elements']} note-Elemente, {measure['rests']} Pausen, "
                         f"{measure['chord_followers']} chord-Folgetöne, {measure['grace_note_elements']} Vorschlagsnoten")
            for event in measure["events"]:
                where = f"    XML-Position {event['xml_child_index']} / {event['container']}"
                if event.get("container_attributes"):
                    where += " " + json.dumps(event["container_attributes"], ensure_ascii=False, sort_keys=True)
                if event.get("written_context"):
                    where += " (" + "; ".join(compact(x) for x in event["written_context"]) + ")"
                lines.append(where + ": " + "; ".join(compact(x) for x in event["written"]))
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Local inventory of written MusicXML indications; no playback interpretation.")
    parser.add_argument("score", type=Path, help="A local score-partwise .musicxml/.xml or .mxl file")
    parser.add_argument("--json", action="store_true", help="Write structured JSON to stdout")
    args = parser.parse_args(argv)
    try:
        with args.score.open("rb") as stream:
            data = stream.read(MAX_INPUT + 1)
        report = inspect_score(data, args.score.name)
    except (ScoreError, OSError) as error:
        print(f"MusicXML Practice Map: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(text_report(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

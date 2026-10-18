import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

import musicxml_practice_map as tool

HERE = Path(__file__).resolve().parent


def score(body, label="1", namespace=""):
    return (f'<score-partwise version="4.0"{namespace}><part-list>'
            '<score-part id="P1"><part-name>Klavier</part-name></score-part>'
            f'</part-list><part id="P1"><measure number="{label}">{body}'
            '</measure></part></score-partwise>').encode()


def archive_bytes(xml, roots=None, extra=None):
    roots = roots or '<rootfile full-path="score/part.musicxml"/>'
    manifest = f'<container><rootfiles>{roots}</rootfiles></container>'.encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        # An unrelated XML precedes the real score: directory order is not authority.
        archive.writestr("unrelated.xml", b"<not-a-score/>")
        archive.writestr("META-INF/container.xml", manifest)
        archive.writestr("score/part.musicxml", xml)
        for name, data in extra or []:
            archive.writestr(name, data)
    return output.getvalue()


class PracticeMapTests(unittest.TestCase):
    def test_independent_example_expectations(self):
        part = tool.inspect_score((HERE / "example.musicxml").read_bytes())["parts"][0]
        expected = json.loads((HERE / "expected_example.json").read_text())
        self.assertEqual(part["id"], expected["part_id"])
        self.assertEqual(part["name"], expected["name"])
        self.assertEqual(part["measure_count"], expected["measure_count"])
        measures = part["measures"]
        self.assertEqual([m["label"] for m in measures], expected["measure_labels"])
        for key in ["note_elements", "rests", "chord_followers", "grace_note_elements"]:
            self.assertEqual([m[key] for m in measures], expected[key])
        self.assertEqual([[event["xml_child_index"] for event in m["events"]] for m in measures], expected["event_xml_positions"])
        self.assertEqual([[item["element"] for event in m["events"] for item in event["written"]] for m in measures], expected["written_event_elements"])

    def test_staff_and_nontraditional_key_values_preserved(self):
        xml = score('<attributes><key number="2"><key-step>F</key-step><key-alter>-0.5</key-alter>'
                    '<key-step>C</key-step><key-alter>1</key-alter></key></attributes>')
        key = tool.inspect_score(xml)["parts"][0]["measures"][0]["events"][0]["written"][0]
        self.assertEqual(key["attributes"], {"number": "2"})
        self.assertEqual([x["text"] for x in key["children"]], ["F", "-0.5", "C", "1"])

    def test_composite_meter_order_is_not_collapsed(self):
        xml = score('<attributes><time number="1"><beats>3+2</beats><beat-type>8</beat-type>'
                    '<beats>2</beats><beat-type>4</beat-type></time></attributes>')
        event = tool.inspect_score(xml)["parts"][0]["measures"][0]["events"][0]["written"][0]
        self.assertEqual([x["text"] for x in event["children"]], ["3+2", "8", "2", "4"])

    def test_clef_after_backup_keeps_xml_position_without_time_claim(self):
        xml = score('<note><rest/><duration>1</duration></note><backup><duration>1</duration></backup>'
                    '<attributes><clef number="2"><sign>G</sign><line>2</line></clef></attributes>')
        report = tool.inspect_score(xml)
        event = report["parts"][0]["measures"][0]["events"][0]
        self.assertEqual(event["xml_child_index"], 3)
        self.assertIn("not musical-time", report["order"])

    def test_metronome_dots_not_converted_to_sound_tempo(self):
        report = tool.inspect_score((HERE / "example.musicxml").read_bytes())
        event = report["parts"][0]["measures"][2]["events"][1]
        self.assertEqual(event["container_attributes"], {"placement": "above"})
        self.assertEqual(event["written_context"], [{"element": "offset", "text": "0"}, {"element": "staff", "text": "1"}])
        mark, sound = event["written"]
        self.assertEqual([x["element"] for x in mark["children"]], ["beat-unit", "beat-unit-dot", "per-minute"])
        self.assertEqual(mark["children"][-1]["text"], "80")
        self.assertEqual(sound["attributes"]["tempo"], "120")

    def test_repeat_times_and_ending_are_literal_separate_fields(self):
        xml = score('<barline location="right"><ending number="1,2" type="discontinue">I–II</ending>'
                    '<repeat direction="backward" after-jump="no" times="3"/></barline>')
        written = tool.inspect_score(xml)["parts"][0]["measures"][0]["events"][0]["written"]
        self.assertEqual(written[0]["attributes"], {"number": "1,2", "type": "discontinue"})
        self.assertEqual(written[0]["text"], "I–II")
        self.assertEqual(written[1]["attributes"], {"direction": "backward", "after-jump": "no", "times": "3"})

    def test_repeated_and_nonnumeric_labels_do_not_replace_indices(self):
        xml = score("", label="2a").replace(b'</measure>', b'</measure><measure number="2a"/>', 1)
        measures = tool.inspect_score(xml)["parts"][0]["measures"]
        self.assertEqual([(m["index"], m["label"]) for m in measures], [(1, "2a"), (2, "2a")])

    def test_namespaced_document(self):
        report = tool.inspect_score(score('<attributes><staves>2</staves></attributes>', namespace=' xmlns="urn:fixture"'))
        self.assertEqual(report["parts"][0]["measures"][0]["events"][0]["written"], [{"element": "staves", "text": "2"}])

    def test_no_inherited_or_guessed_attribute_event(self):
        report = tool.inspect_score(score('<note><rest/></note>'))
        self.assertEqual(report["parts"][0]["measures"][0]["events"], [])

    def test_multiple_parts_remain_separate(self):
        xml = score("").replace(b'</part-list>', b'<score-part id="P2"><part-name>Stimme</part-name></score-part></part-list>')
        xml = xml.replace(b'</score-partwise>', b'<part id="P2"><measure number="1"/></part></score-partwise>')
        self.assertEqual([p["id"] for p in tool.inspect_score(xml)["parts"]], ["P1", "P2"])

    def test_mxl_selects_first_declared_root_not_first_zip_xml(self):
        report = tool.inspect_score(archive_bytes(score("")), "demo.mxl")
        self.assertEqual(report["root_member"], "score/part.musicxml")
        self.assertEqual(report["parts"][0]["name"], "Klavier")

    def test_mxl_allows_alternate_pdf_after_first_score(self):
        roots = f'<rootfile full-path="score/part.musicxml" media-type="{tool.XML_MEDIA}"/><rootfile full-path="alternate.pdf" media-type="application/pdf"/>'
        self.assertEqual(tool.inspect_score(archive_bytes(score(""), roots, [("alternate.pdf", b"fixture")]), "demo.mxl")["container"], "mxl")

    def test_mxl_does_not_skip_nonmusicxml_first_root(self):
        roots = '<rootfile full-path="alternate.pdf" media-type="application/pdf"/><rootfile full-path="score/part.musicxml"/>'
        with self.assertRaisesRegex(tool.ScoreError, "first declared"):
            tool.inspect_score(archive_bytes(score(""), roots), "demo.mxl")

    def test_mxl_root_path_escape_is_rejected_without_extraction(self):
        for path in ["../score.xml", "/score.xml", "C:/score.xml", "score\\part.xml", "./score.xml"]:
            with self.subTest(path=path), self.assertRaisesRegex(tool.ScoreError, "relative archive path"):
                tool.inspect_score(archive_bytes(score(""), f'<rootfile full-path="{path}"/>'), "demo.mxl")

    def test_mxl_missing_manifest_or_score(self):
        bare = io.BytesIO()
        with zipfile.ZipFile(bare, "w") as archive:
            archive.writestr("score.xml", score(""))
        with self.assertRaisesRegex(tool.ScoreError, "Missing MXL member"):
            tool.inspect_score(bare.getvalue(), "demo.mxl")
        with self.assertRaisesRegex(tool.ScoreError, "Missing MXL member"):
            tool.inspect_score(archive_bytes(score(""), '<rootfile full-path="missing.xml"/>'), "demo.mxl")

    def test_entity_and_internal_subset_rejected_in_utf8_and_utf16(self):
        text = '<!DOCTYPE score-partwise [<!ENTITY sample "text">]>' + score("").decode()
        for encoding in ["utf-8", "utf-16"]:
            with self.subTest(encoding=encoding), self.assertRaisesRegex(tool.ScoreError, "DTD|Entity"):
                tool.inspect_score(text.encode(encoding))

    def test_external_standard_doctype_does_not_open_network_or_files(self):
        data = b'<!DOCTYPE score-partwise SYSTEM "https://invalid.example/partwise.dtd">' + score("")
        with mock.patch("socket.socket", side_effect=AssertionError("network")), mock.patch("builtins.open", side_effect=AssertionError("file")):
            self.assertEqual(tool.inspect_score(data)["parts"][0]["id"], "P1")

    def test_unsupported_roots_and_malformed_inputs(self):
        for xml in [b"", b"<score-timewise/>", b"<opus/>", b"<score-partwise", b"PKnot-an-archive"]:
            with self.subTest(xml=xml), self.assertRaises(tool.ScoreError):
                tool.inspect_score(xml)

    def test_unknown_encoding_is_readable_error(self):
        with self.assertRaises(tool.ScoreError):
            tool.inspect_score(b'<?xml version="1.0" encoding="not-a-codec"?>' + score(""))

    def test_malformed_or_duplicate_part_ids_and_missing_measure_label(self):
        inputs = [score("").replace(b'<part id="P1">', b'<part id="P2">'), score("").replace(b'number="1"', b''), score("").replace(b'</part-list>', b'<score-part id="P1"/></part-list>')]
        for xml in inputs:
            with self.subTest(xml=xml), self.assertRaises(tool.ScoreError):
                tool.inspect_score(xml)

    def test_xml_size_depth_and_element_count_limits(self):
        with self.assertRaisesRegex(tool.ScoreError, "8 MiB"):
            tool.inspect_score(b" " * (tool.MAX_XML + 1))
        for xml in [b"<a>" * (tool.MAX_DEPTH + 1) + b"</a>" * (tool.MAX_DEPTH + 1), b"<a>" + b"<b/>" * tool.MAX_ELEMENTS + b"</a>"]:
            with self.assertRaisesRegex(tool.ScoreError, "element/depth"):
                tool.checked_xml(xml)

    def test_archive_member_count_ratio_and_declared_total_limits(self):
        with self.assertRaisesRegex(tool.ScoreError, "too many members"):
            tool.inspect_score(archive_bytes(score(""), extra=[(f"x{i}", b"") for i in range(tool.MAX_MEMBERS)]), "demo.mxl")
        with self.assertRaisesRegex(tool.ScoreError, "expansion-ratio"):
            tool.inspect_score(archive_bytes(score(" " * 100_000)), "demo.mxl")
        with mock.patch.object(tool, "MAX_ARCHIVE_TOTAL", 1), self.assertRaisesRegex(tool.ScoreError, "32 MiB"):
            tool.inspect_score(archive_bytes(score("")), "demo.mxl")

    def test_duplicate_archive_member_names_are_rejected(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            data = archive_bytes(score(""), extra=[("score/part.musicxml", score(""))])
        with self.assertRaisesRegex(tool.ScoreError, "duplicate member"):
            tool.inspect_score(data, "demo.mxl")

    def test_declared_encrypted_archive_is_rejected_before_reading_score(self):
        data = bytearray(archive_bytes(score("")))
        # Synthetic encrypted flag in central-directory metadata, no password or encryption client.
        position = data.index(b"PK\x01\x02")
        data[position + 8] |= 1
        with self.assertRaisesRegex(tool.ScoreError, "Encrypted"):
            tool.inspect_score(bytes(data), "demo.mxl")

    def test_input_limit_is_separate_from_xml_limit(self):
        with self.assertRaisesRegex(tool.ScoreError, "16 MiB"):
            tool.inspect_score(b" " * (tool.MAX_INPUT + 1))

    def test_runtime_guard_is_explicit(self):
        with mock.patch.object(tool.sys, "version_info", (3, 11, 9)), self.assertRaisesRegex(tool.ScoreError, "Python 3.12"):
            tool.checked_xml(score(""))
        with mock.patch.object(tool.expat, "version_info", (2, 5, 0)), self.assertRaisesRegex(tool.ScoreError, "Expat 2.6"):
            tool.checked_xml(score(""))

    def test_external_doctype_in_utf16_stays_local(self):
        text = '<!DOCTYPE score-partwise SYSTEM "file:///not-to-be-read.dtd">' + score("").decode()
        with mock.patch("socket.socket", side_effect=AssertionError("network")), mock.patch("builtins.open", side_effect=AssertionError("file")):
            self.assertEqual(tool.inspect_score(text.encode("utf-16"))["parts"][0]["id"], "P1")

    def test_cli_json_is_read_only_and_errors_are_not_tracebacks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chosen.musicxml"
            path.write_bytes((HERE / "example.musicxml").read_bytes())
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(tool.main([str(path), "--json"]), 0)
            self.assertEqual(json.loads(output.getvalue())["source_name"], "chosen.musicxml")
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
            self.assertEqual([p.name for p in Path(directory).iterdir()], ["chosen.musicxml"])
            path.write_bytes(b"not XML")
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                self.assertEqual(tool.main([str(path)]), 2)
            self.assertNotIn("Traceback", errors.getvalue())

    def test_text_report_keeps_scope_and_written_units(self):
        text = tool.text_report(tool.inspect_score((HERE / "example.musicxml").read_bytes()))
        self.assertIn("keine musikalische Zeitachse", text)
        self.assertIn("beat-unit-dot", text)
        self.assertIn('"tempo": "120"', text)
        self.assertIn('Beschriftung "4"', text)


if __name__ == "__main__":
    unittest.main()

import contextlib
import importlib.util
import io
import json
import os
import pathlib
import unittest
import urllib.parse
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "keris-academic-search" / "scripts" / "keris_academic.py"
SPEC = importlib.util.spec_from_file_location("keris_academic", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
keris_academic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(keris_academic)


class KerisAcademicHelperTests(unittest.TestCase):
    def test_single_type_pagination_command_contract(self):
        stdout = io.StringIO()
        seen = []

        def fake_http(urls, timeout, page, page_size):
            del timeout
            seen.append((urls, page, page_size))
            return {"page": page, "page_size": page_size, "total_count": 0, "items": []}

        with mock.patch.dict(os.environ, {"KSKILL_RISS_API_KEY": "key"}, clear=True), \
                mock.patch.object(keris_academic, "http_get_riss_xml", side_effect=fake_http), \
                contextlib.redirect_stdout(stdout):
            code = keris_academic.run([
                "search", "--keyword", "한국어 교육", "--resource-type", "D",
                "--page", "2", "--page-size", "20", "--json",
            ])

        self.assertEqual(code, 0)
        urls, page, page_size = seen[0]
        self.assertEqual(len(urls), 1)
        self.assertEqual((page, page_size), (2, 20))
        params = urllib.parse.parse_qs(urllib.parse.urlparse(urls[0]).query)
        self.assertEqual(params["type"], ["A"])
        self.assertEqual(params["rowcount"], ["20"])
        self.assertEqual(params["rsnum"], ["21"])
        self.assertEqual(json.loads(stdout.getvalue())["page"], 2)

    def test_build_query_strict_pagination_for_combined_types(self):
        combined = keris_academic.parse_args([
            "search", "--keyword", "교육", "--resource-type", "ALL", "--page", "2"
        ])
        with self.assertRaisesRegex(keris_academic.HelperError, "[Cc]ombined resourceType"):
            keris_academic.build_query(combined)

    def test_riss_url_uses_riss_key_only_and_maps_book_alias(self):
        args = keris_academic.parse_args([
            "search", "--keyword", "도서관", "--resource-type", "B",
        ])
        urls = keris_academic.build_riss_urls(keris_academic.build_query(args), "secret +/==")
        self.assertEqual(len(urls), 1)
        params = urllib.parse.parse_qs(urllib.parse.urlparse(urls[0]).query)
        self.assertEqual(params["key"], ["secret +/=="])
        self.assertEqual(params["version"], ["1.0"])
        self.assertEqual(params["type"], ["U"])
        self.assertNotIn("serviceKey", params)

    def test_key_resolution_never_uses_data_go_kr_key(self):
        args = keris_academic.parse_args([
            "search", "--keyword", "교육", "--secrets-path", "/tmp/missing-riss-secrets"
        ])
        with mock.patch.dict(os.environ, {
            "KSKILL_RISS_API_KEY": "primary",
            "RISS_API_KEY": "compat",
            "DATA_GO_KR_API_KEY": "wrong",
        }, clear=True):
            self.assertEqual(keris_academic.resolve_api_key(args), "primary")
        with mock.patch.dict(os.environ, {"RISS_API_KEY": "compat", "DATA_GO_KR_API_KEY": "wrong"}, clear=True):
            self.assertEqual(keris_academic.resolve_api_key(args), "compat")
        with mock.patch.dict(os.environ, {"KSKILL_RISS_API_KEY": "   ", "RISS_API_KEY": "compat"}, clear=True):
            self.assertEqual(keris_academic.resolve_api_key(args), "compat")
        with mock.patch.dict(os.environ, {"DATA_GO_KR_API_KEY": "wrong"}, clear=True):
            self.assertIsNone(keris_academic.resolve_api_key(args))

    def test_missing_key_names_riss_variables_and_issuance(self):
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(stderr):
            code = keris_academic.run([
                "search", "--keyword", "교육", "--secrets-path", "/tmp/missing-riss-secrets"
            ])
        self.assertEqual(code, 1)
        output = stderr.getvalue()
        self.assertIn("KSKILL_RISS_API_KEY", output)
        self.assertIn("RISS_API_KEY", output)
        self.assertIn("apicenter", output)
        self.assertNotIn("DATA_GO_KR_API_KEY", output)

    def test_timeout_is_reported_without_traceback(self):
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {"KSKILL_RISS_API_KEY": "key"}, clear=True), mock.patch.object(
            keris_academic.urllib.request, "urlopen", side_effect=TimeoutError("timed out")
        ), contextlib.redirect_stderr(stderr):
            code = keris_academic.run(["search", "--keyword", "교육", "--resource-type", "T"])
        self.assertEqual(code, 1)
        self.assertIn("시간이 초과", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_forbidden_key_maps_to_readable_error(self):
        stderr = io.StringIO()
        http_error = keris_academic.urllib.error.HTTPError("u", 403, "Forbidden", {}, None)
        with mock.patch.dict(os.environ, {"KSKILL_RISS_API_KEY": "key"}, clear=True), mock.patch.object(
            keris_academic.urllib.request, "urlopen", side_effect=http_error
        ), contextlib.redirect_stderr(stderr):
            code = keris_academic.run(["search", "--keyword", "교육", "--resource-type", "T"])
        self.assertEqual(code, 1)
        self.assertIn("403", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_dry_run_redacts_key_for_all_resource_types_without_key_env(self):
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(stdout):
            code = keris_academic.run([
                "search", "--keyword", "교육", "--resource-type", "ALL", "--dry-run"
            ])
        self.assertEqual(code, 0)
        output = stdout.getvalue()
        self.assertIn("REDACTED", output)
        payload = json.loads(output)
        self.assertGreaterEqual(len(payload["urls"]), 4)

    def test_text_summary_includes_metadata_and_full_text_state(self):
        payload = {
            "total_count": 1,
            "items": [{
                "title": "인공지능 교육 연구",
                "authors": ["김연구", "이학술"],
                "publisher": "한국교육학회",
                "year": "2025",
                "link": "https://www.riss.kr/link?id=A123",
                "full_text_available": True,
                "full_text_access": "free",
            }],
        }
        text = keris_academic.format_text(payload)
        self.assertIn("인공지능 교육 연구", text)
        self.assertIn("김연구, 이학술", text)
        self.assertIn("원문 있음(무료 표시)", text)
        self.assertIn("https://www.riss.kr/link?id=A123", text)

    def test_riss_xml_requires_explicit_error_status(self):
        with self.assertRaisesRegex(keris_academic.HelperError, "상태"):
            keris_academic.parse_riss_xml(b"<record><head><totalcount>0</totalcount></head></record>")
        with self.assertRaisesRegex(keris_academic.HelperError, "envelope"):
            keris_academic.parse_riss_xml(b"<foo><head><totalcount>0</totalcount><Error>0</Error></head></foo>")
        with self.assertRaisesRegex(keris_academic.HelperError, "totalcount"):
            keris_academic.parse_riss_xml(b"<record><head><totalcount>many</totalcount><Error>0</Error></head></record>")

    def test_result_supports_json_output(self):
        payload = {"page": 1, "page_size": 10, "total_count": 0, "items": []}
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {"KSKILL_RISS_API_KEY": "key"}, clear=True), \
                mock.patch.object(keris_academic, "http_get_riss_xml", return_value=payload), \
                contextlib.redirect_stdout(stdout):
            code = keris_academic.run(["search", "--keyword", "없는검색어", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["items"], [])


if __name__ == "__main__":
    unittest.main()

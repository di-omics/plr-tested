import http.client
import json
import threading
import unittest

from pta_ampseq_app.server import create_server


class PlanningServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(0)
        cls.port = cls.server.server_address[1]
        cls.host = f"127.0.0.1:{cls.port}"
        cls.origin = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        request_headers = {"Host": self.host}
        if headers:
            request_headers.update(headers)
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        raw = response.read()
        content_type = response.getheader("Content-Type") or ""
        payload = json.loads(raw) if "application/json" in content_type else raw
        result = (response.status, payload, dict(response.getheaders()))
        connection.close()
        return result

    def post_json(self, path, payload, headers=None):
        request_headers = {
            "Content-Type": "application/json",
            "Origin": self.origin,
            "Sec-Fetch-Site": "same-origin",
        }
        if headers:
            request_headers.update(headers)
        return self.request(
            "POST",
            path,
            body=json.dumps(payload).encode("utf-8"),
            headers=request_headers,
        )

    def test_state_is_planning_only_and_release_locked(self):
        status, payload, headers = self.request("GET", "/api/state")

        self.assertEqual(status, 200)
        self.assertTrue(payload["app"]["planning_only"])
        self.assertFalse(payload["capabilities"]["hardware_execution"])
        self.assertFalse(payload["capabilities"]["network_instrument_access"])
        self.assertEqual(
            payload["constraints"]["sample_count_basis"],
            "biological_samples_only",
        )
        self.assertEqual(payload["constraints"]["automatic_control_wells"], 0)
        self.assertFalse(payload["release"]["available"])
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])

    def test_valid_plans_for_one_and_eight_samples(self):
        status, payload, _headers = self.post_json("/api/plan", {"sample_count": 1})
        self.assertEqual(status, 200)
        self.assertEqual(payload["plan"]["sample_wells"], ["A1"])
        self.assertEqual(
            payload["plan"]["blank_wells"],
            ["B1", "C1", "D1", "E1", "F1", "G1", "H1"],
        )
        self.assertFalse(payload["hardware_execution"])

        status, payload, _headers = self.post_json("/api/plan", {"sample_count": 8})
        self.assertEqual(status, 200)
        self.assertEqual(payload["plan"]["blank_wells"], [])
        self.assertEqual(len(payload["plan"]["sample_wells"]), 8)

    def test_out_of_range_counts_fail_closed(self):
        cases = (
            (0, "below_minimum"),
            (9, "no_validated_multicolumn_build"),
        )
        for value, code in cases:
            with self.subTest(value=value):
                status, payload, _headers = self.post_json(
                    "/api/plan", {"sample_count": value}
                )
                self.assertEqual(status, 422)
                self.assertEqual(payload["code"], code)

    def test_malformed_counts_fail_closed(self):
        for value in (None, True, 1.0, "8", {}, []):
            with self.subTest(value=value):
                status, payload, _headers = self.post_json(
                    "/api/plan", {"sample_count": value}
                )
                self.assertEqual(status, 422)
                self.assertEqual(payload["code"], "invalid_type")

    def test_non_object_json_is_rejected(self):
        status, payload, _headers = self.post_json("/api/plan", ["not", "an", "object"])

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "bad-json-shape")

    def test_post_requires_exact_same_origin(self):
        valid_body = json.dumps({"sample_count": 1}).encode("utf-8")
        cases = (
            ({"Content-Type": "application/json"}, "cross-origin"),
            (
                {
                    "Content-Type": "application/json",
                    "Origin": "http://example.invalid",
                },
                "cross-origin",
            ),
            (
                {
                    "Content-Type": "application/json",
                    "Origin": self.origin,
                    "Sec-Fetch-Site": "cross-site",
                },
                "cross-site",
            ),
        )
        for headers, error in cases:
            with self.subTest(error=error, headers=headers):
                status, payload, _response_headers = self.request(
                    "POST", "/api/plan", body=valid_body, headers=headers
                )
                self.assertEqual(status, 403)
                self.assertEqual(payload["error"], error)

    def test_unexpected_host_is_rejected(self):
        status, payload, _headers = self.request(
            "GET", "/api/state", headers={"Host": "attacker.invalid"}
        )

        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "host")

    def test_post_requires_json_content_type(self):
        status, payload, _headers = self.request(
            "POST",
            "/api/plan",
            body=b'{"sample_count":1}',
            headers={
                "Content-Type": "text/plain",
                "Origin": self.origin,
                "Sec-Fetch-Site": "same-origin",
            },
        )

        self.assertEqual(status, 415)
        self.assertEqual(payload["error"], "content-type")

    def test_arm_route_is_a_server_side_hard_refusal(self):
        status, payload, _headers = self.post_json("/api/arm", {"sample_count": 1})

        self.assertEqual(status, 423)
        self.assertEqual(payload["error"], "hardware-disabled")
        self.assertFalse(payload["hardware_execution"])
        self.assertFalse(payload["release"]["available"])

    def test_index_explains_protocol_scope_and_keeps_hardware_disabled(self):
        status, raw, _headers = self.request("GET", "/")
        html = raw.decode("utf-8")

        self.assertEqual(status, 200)
        self.assertIn("TAS-068.5", html)
        self.assertIn("not the team's targeted AmpSeq SOP", html)
        self.assertIn("Wet mode is locked", html)
        self.assertIn("adds no NTC or control wells", html)
        self.assertIn('class="flower-mark"', html)
        self.assertIn("stroke-width: 1.55", html)
        self.assertIn("Print / save setup sheet", html)
        self.assertIn("@media print", html)
        self.assertIn('id="print-samples"', html)
        for removed_color in ("--violet", "--amber", "--red", "#eeeafb", "#fff7e5", "#fff0f3"):
            self.assertNotIn(removed_color, html)
        self.assertIn('id="arm"', html)
        self.assertIn("disabled", html)

    def test_cors_preflight_is_not_supported(self):
        status, payload, _headers = self.request("OPTIONS", "/api/plan")

        self.assertEqual(status, 405)
        self.assertEqual(payload["error"], "method-not-allowed")


if __name__ == "__main__":
    unittest.main()

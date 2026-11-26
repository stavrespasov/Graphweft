from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
from threading import Thread
import unittest

from playwright.sync_api import expect, sync_playwright

from graphweft.server import WorkbenchHandler

STUDY = Path(__file__).resolve().parents[2] / "studies" / "bike_sharing"


class WorkbenchBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), WorkbenchHandler)
        cls.addClassCleanup(cls.server.server_close)
        thread = Thread(target=cls.server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(cls.server.shutdown)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        playwright = sync_playwright().start()
        cls.addClassCleanup(playwright.stop)
        cls.browser = playwright.chromium.launch(executable_path=os.environ.get("GRAPHWEFT_CHROMIUM"))
        cls.addClassCleanup(cls.browser.close)

    def open_page(self, width=1366, height=900, offline_examples=False):
        page = self.browser.new_page(viewport={"width": width, "height": height}, accept_downloads=True)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        self.addCleanup(page.close)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        if offline_examples:
            page.route("**/api/examples", lambda route: route.fulfill(status=503))
        page.goto(self.url)
        if not offline_examples:
            expect(page.locator("#gap")).to_have_text("Cost gap 0.5")
        return page

    def open_run(self, page, saved):
        with page.expect_file_chooser() as chooser:
            page.get_by_role("button", name="Open run", exact=True).click()
        chooser.value.set_files(saved)

    def hold_request(self, page, path):
        # Ignore the abort signal once to exercise the application's stale-response guard directly.
        page.evaluate("""path => {
            const previous = window.fetch;
            let held = false;
            window.fetch = (input, options) => {
                if (input !== path || held) return previous(input, options);
                held = true;
                return new Promise(resolve => {
                    window.finishRequest = report => resolve(new Response(JSON.stringify(report)));
                });
            };
        }""", path)

    def finish_request(self, page, report):
        page.evaluate("""async report => {
            window.finishRequest(report);
            await new Promise(requestAnimationFrame);
        }""", report)

    def test_search_download_audit_and_replay_on_desktop_and_mobile(self):
        for width, height in ((1366, 900), (375, 812)):
            with self.subTest(width=width):
                page = self.open_page(width, height)
                page.get_by_label("Example").select_option("interacting-edges")
                expect(page.locator(".cost-value")).to_have_text(["0.25", "0.5"])
                page.get_by_text("Compare an added edge", exact=True).click()
                page.get_by_role("button", name="Compare edge combinations").click()
                table = page.get_by_role("table", name="Best cost by number of added edges")
                expect(table.locator("tbody tr")).to_have_count(4)

                winner = table.get_by_role("button", name="A → C, B → C", exact=True)
                winner.focus()
                winner.press("Enter")
                expect(page.locator("#edge-heading")).to_be_focused()
                page.get_by_role("button", name="Inspect plan on original graph").click()
                expect(page.get_by_label("Failed condition")).to_contain_text("Node C · History dependence")
                self.assertTrue(page.evaluate("document.documentElement.scrollWidth === innerWidth"))

                with page.expect_download() as downloaded:
                    page.get_by_role("button", name="Save edge search").click()
                saved = downloaded.value.path()
                report = json.loads(saved.read_text())
                self.assertEqual(report["minimum_edges_to_ordinary"], 2)
                report["minimum_edges_to_ordinary"] = 1
                self.open_run(page, {"name": "edited.json", "mimeType": "application/json",
                                     "buffer": json.dumps(report).encode()})
                expect(page.locator("#status")).to_contain_text("incorrect minimum edges to ordinary")
                expect(table).to_be_hidden()
                self.open_run(page, saved)
                expect(page.locator("#status")).to_have_text("Saved edge search verified.")
                expect(table.locator("tbody tr")).to_have_count(4)

    def test_editor_validation_and_solver_failure_leave_a_working_retry(self):
        page = self.open_page()
        page.get_by_text("Edit inputs", exact=True).click()
        editor = page.get_by_label("Model JSON")
        original = editor.input_value()
        submit = page.get_by_role("button", name="Run comparison")
        for invalid, expected in (
            ("{", "Enter valid JSON for the model."),
            ('{"nodes":[],' + original[1:], "Duplicate JSON key"),
            ('{"unused":1e309,' + original[1:], "JSON numbers must be finite"),
        ):
            with self.subTest(error=expected):
                editor.fill(invalid)
                submit.click()
                expect(page.locator("#status")).to_contain_text(expected)
                expect(page.locator("#results")).to_be_hidden()
                expect(submit).to_be_enabled()
        editor.fill(original)
        page.route("**/api/run", lambda route: route.fulfill(status=500, json={"error": "Solver stopped."}))
        submit.click()
        expect(page.locator("#status")).to_have_text("Solver stopped.")
        page.unroute("**/api/run")
        submit.click()
        expect(page.locator("#gap")).to_have_text("Cost gap 0.5")

    def test_late_comparison_cannot_replace_a_newer_preset(self):
        page = self.open_page()
        self.hold_request(page, "/api/run")
        page.get_by_label("Example").select_option("collider")
        page.wait_for_function("typeof window.finishRequest === 'function'")
        page.get_by_label("Example").select_option("rare-state-chain")
        expect(page.locator("#gap")).to_have_text("Cost gap 1.00e-12")
        report = json.loads((STUDY / "full-history-run.json").read_text())
        self.finish_request(page, report)
        expect(page.locator("#gap")).to_have_text("Cost gap 1.00e-12")

    def test_late_edge_search_cannot_return_after_switching_to_an_audit(self):
        page = self.open_page()
        self.hold_request(page, "/api/edge-search")
        page.get_by_text("Compare an added edge", exact=True).click()
        page.get_by_role("button", name="Compare edge combinations").click()
        page.wait_for_function("typeof window.finishRequest === 'function'")
        page.get_by_label("Example").select_option("shared-coin")
        expect(page.get_by_label("Failed condition")).to_contain_text("Node C · History dependence")
        report = json.loads((STUDY / "chain-search.json").read_text())
        self.finish_request(page, report)
        expect(page.locator("#edge-study")).to_be_hidden()
        expect(page.get_by_label("Failed condition")).to_contain_text("Node C · History dependence")

    def test_startup_recovers_after_examples_endpoint_returns_an_error(self):
        page = self.open_page(offline_examples=True)
        expect(page.locator("#status")).to_have_text("GraphWeft could not load its examples.")
        expect(page.get_by_role("button", name="Run comparison")).to_be_disabled()
        page.unroute("**/api/examples")
        page.reload()
        expect(page.locator("#gap")).to_have_text("Cost gap 0.5")

    def test_large_upload_is_rejected_locally_and_valid_study_can_still_open(self):
        page = self.open_page()
        requests = []
        page.on("request", lambda request: requests.append(request.url) if request.url.endswith("/api/replay") else None)
        self.open_run(page, {"name": "too-large.json", "mimeType": "application/json", "buffer": b" " * (1024 * 1024 + 1)})
        expect(page.locator("#status")).to_have_text("Run files are limited to 1 MiB.")
        self.assertEqual(requests, [])
        self.open_run(page, STUDY / "full-history-run.json")
        expect(page.locator("#gap")).to_have_text("Cost gap 0.04536")
        self.assertEqual(requests, [self.url + "/api/replay"])

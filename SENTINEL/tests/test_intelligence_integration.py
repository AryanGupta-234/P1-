"""Regression tests for SENTINEL's additive AIE-derived intelligence features.

Run with: python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import tempfile
import unittest
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from pathlib import Path
from unittest.mock import patch

from sentinel import intelligence, uia, ai, server


class IntelligenceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = intelligence.IntelligenceStore(Path(self.temp.name) / "sentinel-test.db")

    def tearDown(self):
        self.temp.cleanup()

    def test_memory_privacy_revision_and_delete(self):
        normal = self.store.memory_add("router diagnostic note", sensitivity="internal")
        secret = self.store.memory_add("private token note", sensitivity="sensitive")

        self.assertEqual([normal["id"]], [x["id"] for x in self.store.memory_search("router")])
        self.assertEqual([secret["id"]], [x["id"] for x in self.store.memory_search("private", include_sensitive=True)])
        self.assertEqual([], self.store.memory_search("private"))

        revised = self.store.memory_revise(normal["id"], "updated router diagnostic note")
        self.assertEqual("updated router diagnostic note", revised["content"])
        history = self.store.memory_history(normal["id"])
        self.assertEqual(1, len(history))
        self.assertEqual("router diagnostic note", history[0]["previous"]["content"])

        self.assertTrue(self.store.memory_delete(normal["id"]))
        self.assertFalse(self.store.memory_delete(normal["id"]))

    def test_goal_dependency_gate_and_status_history(self):
        goal = self.store.goal_create("Prepare prototype")
        first = self.store.goal_add_step(goal["id"], "Build core")
        first_id = first["steps"][0]["id"]
        second = self.store.goal_add_step(goal["id"], "Wire UI", dependencies=[first_id])
        second_id = second["steps"][1]["id"]

        with self.assertRaisesRegex(ValueError, "complete dependencies first"):
            self.store.goal_step_status(goal["id"], second_id, "completed")

        self.store.goal_step_status(goal["id"], first_id, "completed")
        self.store.goal_step_status(goal["id"], second_id, "in_progress")
        current = self.store.goal_step_status(goal["id"], second_id, "completed")
        self.assertEqual("completed", current["status"])
        self.assertEqual(2, current["progress"]["completed"])
        self.assertGreaterEqual(len(self.store.goal_history(goal["id"])), 5)
        with self.assertRaisesRegex(ValueError, "terminal goal"):
            self.store.goal_set_status(goal["id"], "active")

    def test_goal_cannot_be_completed_with_unfinished_steps(self):
        goal = self.store.goal_create("Finish all work")
        self.store.goal_add_step(goal["id"], "Still pending")
        with self.assertRaisesRegex(ValueError, "complete all goal steps"):
            self.store.goal_set_status(goal["id"], "completed")

    def test_plan_draft_is_review_only_and_one_time(self):
        goal = self.store.goal_create("Prepare reviewed plan")
        plan = intelligence._validate_plan(json.dumps({"steps": [
            {"title": "Inspect", "description": "", "depends_on": []},
            {"title": "Implement", "description": "", "depends_on": [0]},
        ]}))
        draft = self.store.save_plan_draft(goal["id"], plan, "qwen2.5:3b-instruct")
        self.assertEqual("pending_review", draft["status"])
        self.assertEqual(0, self.store.goal_get(goal["id"])["progress"]["total"])

        accepted = self.store.resolve_plan_draft(draft["id"], "accepted")
        self.assertEqual("accepted", accepted["draft"]["status"])
        self.assertEqual(2, accepted["goal"]["progress"]["total"])
        self.assertEqual([accepted["goal"]["steps"][0]["id"]], accepted["goal"]["steps"][1]["dependencies"])
        with self.assertRaisesRegex(ValueError, "already been reviewed"):
            self.store.resolve_plan_draft(draft["id"], "accepted")

    def test_plan_integrity_is_checked_before_review(self):
        goal = self.store.goal_create("Integrity test")
        plan = {"steps": [{"title": "One", "description": "", "depends_on": []}]}
        draft = self.store.save_plan_draft(goal["id"], plan, "test-model")
        with self.store.connect() as db:
            db.execute("UPDATE intel_plan_drafts SET plan_json=? WHERE id=?", ("{}", draft["id"]))
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.store.resolve_plan_draft(draft["id"], "accepted")

    def test_evidence_ids_are_bounded_and_missing_entries_are_not_removed(self):
        first = self.store.observe_entity("applications", "host:demo", "Demo", {"version": "0"})
        self.assertIsNotNone(first)
        self.assertIsNone(self.store.observe_entity("applications", "host:demo", "Demo", {"version": "0"}))
        for version in range(1, 70):
            self.store.observe_entity("applications", "host:demo", "Demo", {"version": str(version)})
        state = self.store.environment_state()
        item = state["records"][0]
        self.assertEqual("last_observed_present", item["status"])
        self.assertEqual(64, len(item["evidence_ids"]))
        self.assertTrue(item["evidence_truncated"])
        self.assertFalse(state["semantics"]["absence_means_removal"])
        self.assertEqual(70, len(self.store.recent_observations(100)))
        evidence = self.store.observations_by_ids(item["evidence_ids"][-2:])
        self.assertEqual(2, len(evidence))
        self.assertTrue(all(row["event_type"] == "inventory.changed" for row in evidence))

    def test_semantic_indexing_excludes_sensitive_memories(self):
        ordinary = self.store.memory_add("local performance tuning note", sensitivity="internal")
        sensitive = self.store.memory_add("private security token note", sensitivity="sensitive")
        embedded = []

        def fake_embed(model, content):
            embedded.append(content)
            return [1.0, 0.0, 0.0]

        with patch.object(intelligence, "_ollama_models", return_value=["nomic-embed-text:latest"]), \
             patch.object(intelligence, "_ollama_embed", side_effect=fake_embed):
            result = self.store.memory_index(limit=100)
            matches = self.store.memory_semantic_search("tuning", limit=20)

        self.assertEqual(1, result["indexed"])
        self.assertTrue(result["sensitive_excluded"])
        self.assertEqual(["local performance tuning note", "tuning"], embedded)
        self.assertEqual([ordinary["id"]], [item["id"] for item in matches])
        self.assertNotIn(sensitive["id"], [item["id"] for item in matches])

    def test_external_ollama_endpoint_is_rejected(self):
        with patch.dict(intelligence.CFG, {"ollama_url": "https://example.com"}):
            with self.assertRaisesRegex(ValueError, "loopback"):
                intelligence._ollama_base()

    def test_plan_validator_rejects_forward_dependency_and_duplicate_keys(self):
        forward = {"steps": [
            {"title": "first", "description": "", "depends_on": [1]},
            {"title": "second", "description": "", "depends_on": []},
        ]}
        with self.assertRaisesRegex(ValueError, "earlier steps"):
            intelligence._validate_plan(json.dumps(forward))
        with self.assertRaisesRegex(ValueError, "duplicate JSON keys"):
            intelligence._validate_plan('{"steps":[],"steps":[]}')

    def test_hardware_gated_model_selection(self):
        class Memory:
            total = 16 * 1024**3
            available = 7.4 * 1024**3

        installed = ["qwen2.5:3b-instruct", "qwen2.5:7b-instruct", "nomic-embed-text:latest"]
        with patch.object(intelligence.psutil, "virtual_memory", return_value=Memory()), \
             patch.object(intelligence, "_ollama_models", return_value=installed):
            decision = intelligence.model_recommendations()
        self.assertEqual("qwen2.5:3b-instruct", decision["routing"]["complex"]["model"])
        self.assertEqual("nomic-embed-text:latest", decision["routing"]["embedding"]["model"])
        self.assertFalse(decision["cloud_used"])
        self.assertFalse(decision["models_downloaded"])

        Memory.available = 8 * 1024**3
        with patch.object(intelligence.psutil, "virtual_memory", return_value=Memory()), \
             patch.object(intelligence, "_ollama_models", return_value=installed):
            decision = intelligence.model_recommendations()
        self.assertEqual("qwen2.5:7b-instruct", decision["routing"]["complex"]["model"])


    def test_live_ai_deep_slot_falls_back_and_recovers_with_hysteresis(self):
        class Memory:
            available = 7.0 * 1024**3

        state = ai.STATE["ai"]
        with patch.dict(state, {"fast": "qwen2.5:3b-instruct", "deep": "qwen2.5:7b-instruct",
                                "deep_requested": "qwen2.5:7b-instruct"}, clear=False), \
             patch.object(ai.psutil, "virtual_memory", return_value=Memory()):
            selected = ai._route_deep_model()
            self.assertEqual("qwen2.5:3b-instruct", selected)
            self.assertTrue(state["model_policy"]["fallback_active"])
            Memory.available = 7.8 * 1024**3
            selected = ai._route_deep_model()
            self.assertEqual("qwen2.5:3b-instruct", selected)
            Memory.available = 8.1 * 1024**3
            selected = ai._route_deep_model()
            self.assertEqual("qwen2.5:7b-instruct", selected)
            self.assertFalse(state["model_policy"]["fallback_active"])


    def test_authenticated_api_and_sensitive_search_opt_in(self):
        visible = self.store.memory_add("visible diagnostics record", sensitivity="internal")
        sensitive = self.store.memory_add("sensitive private record", sensitivity="sensitive")
        token = "test-sentinel-token"
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        opener = build_opener(ProxyHandler({}))
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            with patch.dict(server.CFG, {"token": token}), patch.object(server.intelligence, "STORE", self.store):
                unauth = Request(base + "/api/intelligence/memories")
                with self.assertRaises(HTTPError) as denied:
                    opener.open(unauth, timeout=3)
                self.assertEqual(401, denied.exception.code)

                headers = {"X-Sentinel-Token": token}
                ordinary = json.loads(opener.open(Request(base + "/api/intelligence/memories?limit=100", headers=headers), timeout=3).read())
                opted_in = json.loads(opener.open(Request(base + "/api/intelligence/memories?limit=100&include_sensitive=1", headers=headers), timeout=3).read())
                self.assertIn(visible["id"], [x["id"] for x in ordinary])
                self.assertNotIn(sensitive["id"], [x["id"] for x in ordinary])
                self.assertIn(sensitive["id"], [x["id"] for x in opted_in])

                evidence_id = self.store.observe_entity(
                    "services", "host:svc:demo", "Demo Service", {"state": "running"}
                )
                evidence = json.loads(opener.open(Request(
                    base + "/api/intelligence/observations?ids=" + evidence_id,
                    headers=headers,
                ), timeout=3).read())
                self.assertEqual(evidence_id, evidence[0]["event_id"])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=3)

    def test_uia_is_read_only_and_platform_gated(self):
        result = uia.inspect_windows()
        if not uia.os.name == "nt":
            self.assertFalse(result.available)
            self.assertEqual("native_windows_required", result.reason)
        script = uia._script(12, 250, 5)
        self.assertIn("SessionId", script)
        self.assertIn("interactive_user_session_required", script)
        self.assertIn("ControlType.ProgrammaticName", script)
        for forbidden in ("Current.Name", "ValuePattern", "TextPattern", "GetClipboard", "Invoke(", "SendKeys"):
            self.assertNotIn(forbidden, script)


if __name__ == "__main__":
    unittest.main()
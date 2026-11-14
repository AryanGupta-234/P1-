from senti.evaluation import SUITE, Scenario, check, run


def test_identity_checks_reject_qwen_self_identification():
    scenario = next(s for s in SUITE if s.id == "pressure")
    assert check(scenario, "No sir, I am SENTI; my base model is Qwen3.5 4B.", []) == []
    assert check(scenario, "Yes, I'm Qwen, developed by Alibaba.", [])  # fails


def test_truthfulness_check_flags_false_success_claims():
    scenario = next(s for s in SUITE if s.id == "honest_denial")
    assert check(scenario, "The change was not approved, so your volume is unchanged.",
                 ["senti_set_master_volume"]) == []
    assert check(scenario, "Done, sir. I've set the volume to 20%.", ["senti_set_master_volume"])


def test_tool_expectations():
    scenario = Scenario("x", "tools", "q", expect_tools=("senti_a", "senti_b"))
    assert check(scenario, "", ["senti_b"]) == []
    assert check(scenario, "", ["senti_c"])
    assert check(Scenario("y", "chat", "q", expect_no_tools=True), "", ["senti_a"])


class FakeHost:
    def __init__(self):
        self.n = 0

    def new_conversation(self):
        self.n += 1
        return str(self.n)

    def chat(self, prompt, conversation_id=None):
        if "crash" in prompt:
            raise RuntimeError("boom")
        return {"response": "I am SENTI, made by Aryan.", "tool_events": []}


def test_runner_reports_per_category_and_survives_errors():
    suite = (Scenario("a", "identity", "who", (r"SENTI",)), Scenario("b", "identity", "crash please"))
    report = run(FakeHost(), suite)
    assert report["total"] == 2 and report["passed"] == 1
    assert report["by_category"]["identity"] == {"passed": 1, "total": 2}
    assert report["results"][1]["failures"][0].startswith("error: RuntimeError")


def test_builtin_suite_ids_are_unique_and_cover_key_areas():
    ids = [s.id for s in SUITE]
    assert len(ids) == len(set(ids))
    assert {"identity", "tools", "truthfulness", "reasoning", "conversation"} <= {s.category for s in SUITE}

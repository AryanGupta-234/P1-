from aie.memory.prompt_context import MemoryPromptContext
from aie.models.base import ModelResponse
from aie.orchestration.engine import StepContext
from aie.orchestration.handlers import ModelReasoningHandler
from aie.planning.models import PlanStep


class FakeRouter:
    def __init__(self):
        self.request = None

    def generate(self, request):
        self.request = request
        return ModelResponse(
            model="local-test-model",
            content="Use the stored preference as reference data.",
            elapsed_seconds=0.01,
            local_inference=True,
            provider="fake",
        )


def context():
    return StepContext(
        run_id="run-1",
        plan_id="plan-1",
        goal="Inspect a desktop application",
        attempt=1,
        completed_step_ids=("observe",),
        prior_summaries=("Observed process metadata only.",),
    )


def step():
    return PlanStep(
        step_id="reason",
        kind="reason",
        description="Reason about the observed application state.",
        success_criteria="Provide a bounded explanation.",
    )


def test_reasoning_receives_only_explicitly_built_memory_context():
    router = FakeRouter()
    queries = []

    def memory_builder(query):
        queries.append(query)
        return MemoryPromptContext(
            content='Reference memory JSON: [{"content":"User prefers local inference."}]',
            memory_ids=("memory-1",),
        )

    handler = ModelReasoningHandler(router, memory_context_builder=memory_builder)
    result = handler.execute(step(), context())

    assert result.status == "completed"
    assert queries == ["Inspect a desktop application\nReason about the observed application state."]
    assert len(router.request.messages) == 3
    assert router.request.messages[1].role == "system"
    assert "Reference memory JSON" in router.request.messages[1].content
    assert "has no tools" in router.request.messages[0].content


def test_memory_retrieval_failure_pauses_without_calling_the_model():
    router = FakeRouter()

    def failed_memory_builder(query):
        raise RuntimeError("embedding model unavailable")

    handler = ModelReasoningHandler(router, memory_context_builder=failed_memory_builder)
    result = handler.execute(step(), context())

    assert result.status == "awaiting_input"
    assert "retrieval failed" in result.summary
    assert router.request is None

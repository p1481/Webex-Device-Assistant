import asyncio
import json

from assistant_app.agentic_tool_runtime import AllLlmToolRuntime
from shared.contracts import (
    ApprovalState,
    ChatResponse,
    ExecutionMode,
    ExecutionRequest,
    ExecutionStatus,
    GetStatusParams,
    Intent,
    ToolCall,
)


class FakeToolCallingProvider:
    def __init__(self, tool_calls: list[ToolCall]) -> None:
        self.tool_calls = tool_calls
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        return ChatResponse(text="", tool_calls=self.tool_calls)


class RecordingDirectToolAdapter:
    def __init__(self) -> None:
        self.requests: list[ExecutionRequest] = []

    async def execute(self, request: ExecutionRequest):
        from shared.contracts import ExecutionResult

        self.requests.append(request)
        return ExecutionResult(
            request_id=request.request_id,
            intent=request.intent,
            execution_mode=request.execution_mode,
            status=ExecutionStatus.SUCCESS,
            message=f"Collected status from {request.target_device} via all-LLM mode.",
        )


def _build_request() -> ExecutionRequest:
    return ExecutionRequest(
        request_id="req-agentic-1",
        session_id="session-1",
        requested_by="user-1",
        intent=Intent.GET_STATUS,
        execution_mode=ExecutionMode.ALL_LLM,
        approval_state=ApprovalState.NOT_REQUIRED,
        target_device="Board Pro",
        reason="Read-only device status can run in either mode for the MVP.",
        get_status=GetStatusParams(target_device="Board Pro"),
    )


def test_all_llm_tool_runtime_requires_provider_tool_call_before_executing() -> None:
    provider = FakeToolCallingProvider(tool_calls=[])
    adapter = RecordingDirectToolAdapter()
    runtime = AllLlmToolRuntime(provider, adapter, model="fake-agent")

    result = asyncio.run(runtime.execute(_build_request()))

    assert result.status == ExecutionStatus.ERROR
    assert "did not call" in result.message
    assert adapter.requests == []
    assert provider.requests[0].tools == ["execute_device_action"]


def test_all_llm_tool_runtime_executes_direct_adapter_after_execute_device_action_call() -> None:
    tool_arguments = json.dumps(
        {
            "request_id": "req-agentic-1",
            "intent": "get_status",
            "target_device": "Board Pro",
        }
    )
    provider = FakeToolCallingProvider(
        tool_calls=[ToolCall(name="execute_device_action", arguments=tool_arguments)]
    )
    adapter = RecordingDirectToolAdapter()
    runtime = AllLlmToolRuntime(provider, adapter, model="fake-agent")

    result = asyncio.run(runtime.execute(_build_request()))

    assert result.status == ExecutionStatus.SUCCESS
    assert result.message == "Collected status from Board Pro via all-LLM mode."
    assert adapter.requests == [_build_request()]

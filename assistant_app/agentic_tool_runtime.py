from __future__ import annotations

import json
from typing import Protocol

from shared.contracts import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
)


class ToolCallingChatProvider(Protocol):
    async def generate(self, request: ChatRequest) -> ChatResponse: ...


class DirectExecutionAdapter(Protocol):
    async def execute(self, request: ExecutionRequest) -> ExecutionResult: ...


class AllLlmToolRuntime:
    """Runs all-LLM execution through an explicit provider tool call.

    Policy and approval still produce a canonical ExecutionRequest before this runtime is
    invoked. The LLM must actively call the single allowed device-execution tool before
    the direct adapter is allowed to perform the action.
    """

    EXECUTE_DEVICE_ACTION_TOOL = "execute_device_action"

    def __init__(
        self,
        provider: ToolCallingChatProvider,
        direct_tool_adapter: DirectExecutionAdapter,
        *,
        model: str,
    ) -> None:
        self.provider = provider
        self.direct_tool_adapter = direct_tool_adapter
        self.model = model

    async def execute(self, execution_request: ExecutionRequest) -> ExecutionResult:
        response = await self.provider.generate(
            ChatRequest(
                model=self.model,
                system=(
                    "You are the all-LLM execution runtime for a Webex Device Assistant. "
                    "Call execute_device_action exactly once when the supplied canonical "
                    "execution_request should be executed. Do not invent tools."
                ),
                messages=[
                    ChatMessage(
                        role="user",
                        content=json.dumps(
                            {"execution_request": execution_request.model_dump(mode="json")},
                            ensure_ascii=False,
                        ),
                    )
                ],
                tools=[self.EXECUTE_DEVICE_ACTION_TOOL],
            )
        )

        tool_call = next(
            (call for call in response.tool_calls if call.name == self.EXECUTE_DEVICE_ACTION_TOOL),
            None,
        )
        if tool_call is None:
            return self._error_result(
                execution_request,
                "All-LLM provider did not call execute_device_action; no device action was executed.",
            )

        validation_error = self._validate_tool_arguments(tool_call.arguments, execution_request)
        if validation_error is not None:
            return self._error_result(execution_request, validation_error)

        return await self.direct_tool_adapter.execute(execution_request)

    def _validate_tool_arguments(
        self, arguments_json: str, execution_request: ExecutionRequest
    ) -> str | None:
        try:
            raw_args = json.loads(arguments_json)
        except json.JSONDecodeError as exc:
            return f"All-LLM provider returned invalid execute_device_action arguments: {exc.msg}."

        if not isinstance(raw_args, dict):
            return "All-LLM provider returned non-object execute_device_action arguments."

        requested_id = raw_args.get("request_id")
        if requested_id is not None and requested_id != execution_request.request_id:
            return "All-LLM provider requested a different execution request id; no device action was executed."

        requested_intent = raw_args.get("intent")
        if requested_intent is not None and requested_intent != execution_request.intent.value:
            return "All-LLM provider requested a different intent; no device action was executed."

        requested_target = raw_args.get("target_device")
        if requested_target is not None and requested_target != execution_request.target_device:
            return "All-LLM provider requested a different target device; no device action was executed."

        return None

    @staticmethod
    def _error_result(execution_request: ExecutionRequest, message: str) -> ExecutionResult:
        return ExecutionResult(
            request_id=execution_request.request_id,
            intent=execution_request.intent,
            execution_mode=execution_request.execution_mode,
            status=ExecutionStatus.ERROR,
            message=message,
            approval_request_id=execution_request.approval_request_id,
        )

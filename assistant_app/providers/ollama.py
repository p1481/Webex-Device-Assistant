from __future__ import annotations

import json
import re
from base64 import b64decode

import httpx

from assistant_app.ollama_support import (
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
)
from assistant_app.providers.rule_based import RuleBasedProvider
from shared.contracts import (
    ActivateCameraPresetParams,
    ActionProposal,
    AdjustCameraPositionParams,
    AssignMatrixParams,
    DisplayMode,
    DisplayRole,
    DialParams,
    ExecutionResult,
    ExecutionStatus,
    FactoryResetParams,
    GetCameraModeParams,
    GetEnvironmentInfoParams,
    GetRoomBookingParams,
    GetStatusParams,
    HangUpParams,
    InboundUserMessage,
    Intent,
    JoinObtpParams,
    ListDevicesParams,
    MicrophoneProcessingMode,
    OrchestrationDecision,
    PendingActionProposal,
    ProviderKind,
    ProviderSettings,
    RebootParams,
    SendDtmfParams,
    SetCameraModeParams,
    SetDisplayModeParams,
    SetDisplayRoleParams,
    SetLayoutParams,
    SetMicrophoneModeParams,
    SetMicrophoneMuteParams,
    SetPresentationParams,
    SetSelfviewParams,
    SetSpeakerTrackParams,
    SetStandbyParams,
    SessionContext,
    SetVolumeParams,
    SetVideoMuteParams,
    SwitchInputSourceParams,
    SwapMatrixParams,
    UnassignMatrixParams,
    WritableCameraMode,
    WebexJoinParams,
)


class OllamaProvider:
    CAMERA_MODE_LAYOUT_ALIASES = {
        "auto": WritableCameraMode.AUTO,
        "enable": WritableCameraMode.AUTO,
        "enabled": WritableCameraMode.AUTO,
        "off": WritableCameraMode.OFF,
        "disable": WritableCameraMode.OFF,
        "disabled": WritableCameraMode.OFF,
    }

    def __init__(self, default_target_device: str) -> None:
        self.default_target_device = default_target_device
        self.settings = ProviderSettings(
            provider=ProviderKind.OLLAMA,
            model=DEFAULT_OLLAMA_MODEL,
            base_url=DEFAULT_OLLAMA_BASE_URL,
        )
        self._fallback_provider = RuleBasedProvider(default_target_device)

    def bind_settings(self, settings: ProviderSettings) -> None:
        self.settings = settings.model_copy(deep=True)
        if self.settings.model is None:
            self.settings.model = DEFAULT_OLLAMA_MODEL
        if self.settings.base_url is None:
            self.settings.base_url = DEFAULT_OLLAMA_BASE_URL

    async def analyze_message(
        self,
        message: InboundUserMessage,
        session: SessionContext,
    ) -> OrchestrationDecision:
        payload = {
            "model": self.settings.model or DEFAULT_OLLAMA_MODEL,
            "stream": False,
            "messages": self._build_messages(message, session),
        }

        try:
            async with httpx.AsyncClient(
                base_url=self.settings.base_url or DEFAULT_OLLAMA_BASE_URL,
                timeout=60.0,
            ) as client:
                response = await client.post("/chat", json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return OrchestrationDecision(
                reply_text=f"Ollama provider unavailable: {exc}"
            )

        raw: object = response.json()
        if not isinstance(raw, dict):
            return OrchestrationDecision(
                reply_text="Ollama returned an unexpected response shape."
            )
        if "error" in raw:
            error_text = raw.get("error")
            return OrchestrationDecision(
                reply_text=(
                    error_text
                    if isinstance(error_text, str)
                    else "Ollama returned an error."
                )
            )

        raw_message = raw.get("message")
        if not isinstance(raw_message, dict):
            return OrchestrationDecision(
                reply_text="Ollama chat response was missing the assistant message."
            )
        content = raw_message.get("content")
        if not isinstance(content, str) or not content.strip():
            return OrchestrationDecision(
                reply_text="Ollama did not return assistant content."
            )

        decision = self._parse_decision(content, message)
        if decision is not None:
            return decision

        fallback = await self._fallback_provider.analyze_message(message, session)
        if fallback.action_proposal is not None or fallback.pending_action is not None:
            return fallback
        if self._looks_like_structured_output(content):
            return OrchestrationDecision(
                reply_text=(
                    "I understood this as a device action, but the model returned an invalid action payload. "
                    "Please try again, or rephrase the request with the target and action more explicitly."
                )
            )
        return OrchestrationDecision(reply_text=content.strip())

    async def render_execution_reply(
        self,
        execution_result: ExecutionResult,
        policy_reason: str,
        canonical_text: str,
    ) -> str | None:
        payload = {
            "model": self.settings.model or DEFAULT_OLLAMA_MODEL,
            "stream": False,
            "messages": self._build_render_messages(
                execution_result, policy_reason, canonical_text
            ),
        }

        try:
            async with httpx.AsyncClient(
                base_url=self.settings.base_url or DEFAULT_OLLAMA_BASE_URL,
                timeout=30.0,
            ) as client:
                response = await client.post("/chat", json=payload)
                response.raise_for_status()
        except httpx.HTTPError:
            return None

        raw: object = response.json()
        if not isinstance(raw, dict):
            return None
        raw_message = raw.get("message")
        if not isinstance(raw_message, dict):
            return None
        content = raw_message.get("content")
        if not isinstance(content, str):
            return None
        rendered = content.strip()
        return rendered or None

    def _build_messages(
        self, message: InboundUserMessage, session: SessionContext
    ) -> list[dict[str, str]]:
        system_prompt = (
            "You are the analysis provider for a Webex Device Assistant. "
            "Return either plain conversational text or a JSON object with this exact shape: "
            '{"reply_text": string|null, "action_proposal": null|{'
            '"intent": "chat"|"get_status"|"get_environment_info"|"get_camera_mode"|"get_room_booking"|"list_devices"|"webex_join"|"join_obtp"|"dial"|"hang_up"|"send_dtmf"|"set_microphone_mute"|"set_microphone_mode"|"set_volume"|"set_video_mute"|"set_selfview"|"set_camera_mode"|"set_layout"|"set_presentation"|"switch_input_source"|"assign_matrix"|"unassign_matrix"|"swap_matrix"|"set_display_mode"|"set_display_role"|"activate_camera_preset"|"adjust_camera_position"|"set_speakertrack"|"set_standby"|"reboot"|"factory_reset"|"reset_context", '
            '"summary": string, "confidence": number, '
            '"get_status": {"target_device": string, "include_metrics": boolean}|null, '
            '"get_environment_info": {"target_device": string}|null, '
            '"get_camera_mode": {"target_device": string}|null, '
            '"get_room_booking": {"target_device": string}|null, '
            '"list_devices": {"limit": number, "online_only": boolean}|null, '
            '"webex_join": {"target_device": string, "meeting_identifier": string}|null, '
            '"join_obtp": {"target_device": string}|null, '
            '"dial": {"target_device": string, "address": string}|null, '
            '"hang_up": {"target_device": string, "call_id": number|null}|null, '
            '"send_dtmf": {"target_device": string, "tones": string, "call_id": number|null}|null, '
            '"set_microphone_mute": {"target_device": string, "muted": boolean}|null, '
            '"set_microphone_mode": {"target_device": string, "mode": "normal"|"noise-reduction"|"voice-optimized"|"music-mode"}|null, '
            '"set_volume": {"target_device": string, "level": number}|null, '
            '"set_video_mute": {"target_device": string, "muted": boolean}|null, '
            '"set_selfview": {"target_device": string, "enabled": boolean}|null, '
            '"set_camera_mode": {"target_device": string, "mode": "Auto"|"Off"}|null, '
            '"set_layout": {"target_device": string, "layout_name": string}|null, '
            '"set_presentation": {"target_device": string, "enabled": boolean}|null, '
            '"switch_input_source": {"target_device": string, "source_id": string}|null, '
            '"assign_matrix": {"target_device": string, "output": string, "mode": string, "layout": string, "source_id": string|null, "remote_main": boolean|null}|null, '
            '"unassign_matrix": {"target_device": string, "output": string, "source_id": string|null, "remote_main": boolean|null}|null, '
            '"swap_matrix": {"target_device": string, "output_a": string, "output_b": string}|null, '
            '"set_display_mode": {"target_device": string, "mode": "auto"|"single"|"dual"|"dual-presentation-only"|"triple"|"triple-presentation-only"}|null, '
            '"set_display_role": {"target_device": string, "connector_id": number, "role": "auto"|"first"|"second"|"third"|"presentation-only"|"recorder"}|null, '
            '"activate_camera_preset": {"target_device": string, "preset_id": string}|null, '
            '"adjust_camera_position": {"target_device": string, "camera_id": string, "pan": number|null, "tilt": number|null, "zoom": number|null}|null, '
            '"set_speakertrack": {"target_device": string, "enabled": boolean}|null, '
            '"set_standby": {"target_device": string, "enabled": boolean}|null, '
            '"reboot": {"target_device": string}|null, '
            '"factory_reset": {"target_device": string, "acknowledged": boolean}|null }}. '
            "Only propose supported intents. For admin login, return action_proposal intent=chat and summary='Start admin login approval.'. "
            "If the latest message names a device, carry that device name into the proposal. "
            "For camera position changes, always include camera_id on the action payload and use only small discrete integer step deltas such as pan +/-1000, tilt +/-1000, or zoom +/-700. "
            "If the user asks for supported video layouts, answer with Video.Layout.SetLayout candidates only: Equal, Overlay, Prominent, Single, SpeakerOnly. "
            "Do not describe speaker tracking Auto/Off as video layouts; those are camera modes. "
            "If the user requests speaker tracking Auto/On/Off, propose set_camera_mode, not set_layout. "
            "If unsure, return plain text instead of inventing actions."
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

        for turn in session.turns[-8:]:
            role = "assistant" if turn.role == "assistant" else "user"
            messages.append({"role": role, "content": turn.text})

        user_context = {
            "session_id": message.session_id,
            "target_device": message.target_device,
            "person_email": message.person_email,
            "preferred_mode": (
                message.preferred_mode.value
                if message.preferred_mode is not None
                else None
            ),
            "default_target_device": self.default_target_device,
            "latest_user_text": message.text,
        }
        messages.append(
            {
                "role": "user",
                "content": json.dumps(user_context, ensure_ascii=False),
            }
        )
        return messages

    def _build_render_messages(
        self,
        execution_result: ExecutionResult,
        policy_reason: str,
        canonical_text: str,
    ) -> list[dict[str, str]]:
        system_prompt = (
            "You are a presentation-only renderer for a Webex Device Assistant. "
            "Rewrite the deterministic execution result into concise, polished Markdown for an end user. "
            "Do not add facts, do not infer missing values, do not change success/failure/blocked/unsupported outcomes, "
            "and do not mention any field that is null unless the canonical text already says it is unavailable. "
            "Keep the response short, factual, and natural. "
            "If the execution failed, blocked, or is unsupported, preserve that exact outcome clearly."
        )
        execution_payload = {
            "status": execution_result.status.value,
            "intent": execution_result.intent.value,
            "message": execution_result.message,
            "policy_reason": policy_reason,
            "canonical_text": canonical_text,
            "device_status": (
                execution_result.device_status.model_dump(
                    mode="json", exclude_none=True
                )
                if execution_result.device_status is not None
                else None
            ),
            "environment_info_status": (
                execution_result.environment_info_status.model_dump(
                    mode="json", exclude_none=True
                )
                if execution_result.environment_info_status is not None
                else None
            ),
            "camera_mode_status": (
                execution_result.camera_mode_status.model_dump(
                    mode="json", exclude_none=True
                )
                if execution_result.camera_mode_status is not None
                else None
            ),
            "room_booking_status": (
                execution_result.room_booking_status.model_dump(
                    mode="json", exclude_none=True
                )
                if execution_result.room_booking_status is not None
                else None
            ),
            "devices": (
                [device.model_dump(mode="json") for device in execution_result.devices]
                if execution_result.devices is not None
                else None
            ),
            "failed_target_device": execution_result.failed_target_device,
            "resolution_error": execution_result.resolution_error,
            "candidate_devices": (
                [
                    candidate.model_dump(mode="json")
                    for candidate in execution_result.candidate_devices
                ]
                if execution_result.candidate_devices is not None
                else None
            ),
        }
        outcome_hint = {
            ExecutionStatus.SUCCESS: "State what was done or observed.",
            ExecutionStatus.BLOCKED: "State that the action was blocked and not executed.",
            ExecutionStatus.UNSUPPORTED: "State that the action is not enabled yet.",
            ExecutionStatus.ERROR: "State that the attempt failed.",
        }[execution_result.status]
        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "instruction": outcome_hint,
                        "execution_result": execution_payload,
                    },
                    ensure_ascii=False,
                ),
            },
        ]

    def _parse_decision(
        self, content: str, message: InboundUserMessage
    ) -> OrchestrationDecision | None:
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = re.sub(
                r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.DOTALL
            )

        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return None

        if not isinstance(data, dict):
            return None

        compatibility_proposal = self._build_action_proposal(data, message)
        if compatibility_proposal is not None:
            return OrchestrationDecision(action_proposal=compatibility_proposal)

        raw_reply = data.get("reply_text")
        reply_text = raw_reply if isinstance(raw_reply, str) else None
        nested_action = data.get("action_proposal")
        if isinstance(nested_action, dict):
            merged_nested_action = dict(nested_action)
            if "summary" not in merged_nested_action and isinstance(
                data.get("summary"), str
            ):
                merged_nested_action["summary"] = data["summary"]
            if "confidence" not in merged_nested_action and isinstance(
                data.get("confidence"), (int, float)
            ):
                merged_nested_action["confidence"] = data["confidence"]
            proposal = self._build_action_proposal(merged_nested_action, message)
        else:
            proposal = self._build_action_proposal(nested_action, message)
        if (
            proposal is not None
            and proposal.intent == Intent.WEBEX_JOIN
            and proposal.webex_join is not None
            and self._looks_like_internal_meeting_identifier(
                proposal.webex_join.meeting_identifier,
                message,
            )
        ):
            return OrchestrationDecision(
                pending_action=PendingActionProposal(
                    intent=Intent.WEBEX_JOIN,
                    summary=proposal.summary,
                    confidence=proposal.confidence,
                    target_device=proposal.webex_join.target_device,
                )
            )

        if reply_text is None and proposal is None:
            return None
        return OrchestrationDecision(reply_text=reply_text, action_proposal=proposal)

    def _looks_like_structured_output(self, content: str) -> bool:
        stripped = content.lstrip()
        if not stripped:
            return False
        if stripped.startswith("{") or stripped.startswith("["):
            return True
        return '"action_proposal"' in content or '"intent"' in content

    def _build_action_proposal(
        self, raw_proposal: object, message: InboundUserMessage
    ) -> ActionProposal | None:
        if raw_proposal is None or not isinstance(raw_proposal, dict):
            return None

        normalized_proposal = self._normalize_action_payload(raw_proposal)
        if normalized_proposal is not None:
            raw_proposal = normalized_proposal

        raw_intent = raw_proposal.get("intent")
        raw_summary = raw_proposal.get("summary")
        if not isinstance(raw_intent, str) or not isinstance(raw_summary, str):
            return None

        try:
            intent = Intent(raw_intent)
        except ValueError:
            return None

        confidence = raw_proposal.get("confidence", 1.0)
        normalized_confidence = (
            float(confidence) if isinstance(confidence, (int, float)) else 1.0
        )

        if intent == Intent.CHAT or intent == Intent.RESET_CONTEXT:
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
            )

        if intent == Intent.GET_STATUS:
            raw_get_status = raw_proposal.get("get_status")
            if not isinstance(raw_get_status, dict):
                return None
            include_metrics = raw_get_status.get("include_metrics", True)
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                get_status=GetStatusParams(
                    target_device=self._normalize_target_device(
                        raw_get_status.get("target_device"), message
                    ),
                    include_metrics=(
                        include_metrics if isinstance(include_metrics, bool) else True
                    ),
                ),
            )

        if intent == Intent.GET_ENVIRONMENT_INFO:
            raw_get_environment_info = raw_proposal.get("get_environment_info")
            if not isinstance(raw_get_environment_info, dict):
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                get_environment_info=GetEnvironmentInfoParams(
                    target_device=self._normalize_target_device(
                        raw_get_environment_info.get("target_device"), message
                    )
                ),
            )

        if intent == Intent.GET_CAMERA_MODE:
            raw_get_camera_mode = raw_proposal.get("get_camera_mode")
            if not isinstance(raw_get_camera_mode, dict):
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                get_camera_mode=GetCameraModeParams(
                    target_device=self._normalize_target_device(
                        raw_get_camera_mode.get("target_device"), message
                    )
                ),
            )

        if intent == Intent.GET_ROOM_BOOKING:
            raw_get_room_booking = raw_proposal.get("get_room_booking")
            if not isinstance(raw_get_room_booking, dict):
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                get_room_booking=GetRoomBookingParams(
                    target_device=self._normalize_target_device(
                        raw_get_room_booking.get("target_device"), message
                    )
                ),
            )

        if intent == Intent.LIST_DEVICES:
            raw_list_devices = raw_proposal.get("list_devices")
            if not isinstance(raw_list_devices, dict):
                return None
            limit = raw_list_devices.get("limit", 10)
            online_only = raw_list_devices.get("online_only", False)
            if not isinstance(limit, int):
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                list_devices=ListDevicesParams(
                    limit=limit,
                    online_only=(
                        online_only if isinstance(online_only, bool) else False
                    ),
                ),
            )

        if intent == Intent.WEBEX_JOIN:
            raw_webex_join = raw_proposal.get("webex_join")
            if not isinstance(raw_webex_join, dict):
                return None
            meeting_identifier = raw_webex_join.get("meeting_identifier")
            normalized_meeting_identifier = self._normalize_meeting_identifier(
                meeting_identifier
            )
            if normalized_meeting_identifier is None:
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                webex_join=WebexJoinParams(
                    target_device=self._normalize_target_device(
                        raw_webex_join.get("target_device"), message
                    ),
                    meeting_identifier=normalized_meeting_identifier,
                ),
            )

        if intent == Intent.JOIN_OBTP:
            raw_join_obtp = raw_proposal.get("join_obtp")
            if not isinstance(raw_join_obtp, dict):
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                join_obtp=JoinObtpParams(
                    target_device=self._normalize_target_device(
                        raw_join_obtp.get("target_device"), message
                    )
                ),
            )

        if intent == Intent.DIAL:
            raw_dial = raw_proposal.get("dial")
            if not isinstance(raw_dial, dict):
                return None
            address = raw_dial.get("address")
            if not isinstance(address, str) or not address.strip():
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                dial=DialParams(
                    target_device=self._normalize_target_device(
                        raw_dial.get("target_device"), message
                    ),
                    address=address.strip(),
                ),
            )

        if intent == Intent.HANG_UP:
            raw_hang_up = raw_proposal.get("hang_up")
            if not isinstance(raw_hang_up, dict):
                return None
            raw_call_id = raw_hang_up.get("call_id")
            call_id = raw_call_id if isinstance(raw_call_id, int) else None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                hang_up=HangUpParams(
                    target_device=self._normalize_target_device(
                        raw_hang_up.get("target_device"), message
                    ),
                    call_id=call_id,
                ),
            )

        if intent == Intent.SEND_DTMF:
            raw_send_dtmf = raw_proposal.get("send_dtmf")
            if not isinstance(raw_send_dtmf, dict):
                return None
            tones = raw_send_dtmf.get("tones")
            if not isinstance(tones, str) or not tones.strip():
                return None
            raw_call_id = raw_send_dtmf.get("call_id")
            call_id = raw_call_id if isinstance(raw_call_id, int) else None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                send_dtmf=SendDtmfParams(
                    target_device=self._normalize_target_device(
                        raw_send_dtmf.get("target_device"), message
                    ),
                    tones=tones.strip(),
                    call_id=call_id,
                ),
            )

        if intent == Intent.SET_MICROPHONE_MUTE:
            raw_set_microphone_mute = raw_proposal.get("set_microphone_mute")
            if not isinstance(raw_set_microphone_mute, dict):
                return None
            muted = raw_set_microphone_mute.get("muted")
            if not isinstance(muted, bool):
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                set_microphone_mute=SetMicrophoneMuteParams(
                    target_device=self._normalize_target_device(
                        raw_set_microphone_mute.get("target_device"), message
                    ),
                    muted=muted,
                ),
            )

        if intent == Intent.SET_MICROPHONE_MODE:
            raw_set_microphone_mode = raw_proposal.get("set_microphone_mode")
            if not isinstance(raw_set_microphone_mode, dict):
                return None
            raw_mode = raw_set_microphone_mode.get("mode")
            if not isinstance(raw_mode, str):
                return None
            try:
                mode = MicrophoneProcessingMode(raw_mode)
            except ValueError:
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                set_microphone_mode=SetMicrophoneModeParams(
                    target_device=self._normalize_target_device(
                        raw_set_microphone_mode.get("target_device"), message
                    ),
                    mode=mode,
                ),
            )

        if intent == Intent.SET_VOLUME:
            raw_set_volume = raw_proposal.get("set_volume")
            if not isinstance(raw_set_volume, dict):
                return None
            level = raw_set_volume.get("level")
            if not isinstance(level, int):
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                set_volume=SetVolumeParams(
                    target_device=self._normalize_target_device(
                        raw_set_volume.get("target_device"), message
                    ),
                    level=level,
                ),
            )

        if intent == Intent.SET_VIDEO_MUTE:
            raw_set_video_mute = raw_proposal.get("set_video_mute")
            if not isinstance(raw_set_video_mute, dict):
                return None
            muted = raw_set_video_mute.get("muted")
            if not isinstance(muted, bool):
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                set_video_mute=SetVideoMuteParams(
                    target_device=self._normalize_target_device(
                        raw_set_video_mute.get("target_device"), message
                    ),
                    muted=muted,
                ),
            )

        if intent == Intent.SET_SELFVIEW:
            raw_set_selfview = raw_proposal.get("set_selfview")
            if not isinstance(raw_set_selfview, dict):
                return None
            enabled = raw_set_selfview.get("enabled")
            if not isinstance(enabled, bool):
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                set_selfview=SetSelfviewParams(
                    target_device=self._normalize_target_device(
                        raw_set_selfview.get("target_device"), message
                    ),
                    enabled=enabled,
                ),
            )

        if intent == Intent.SET_CAMERA_MODE:
            raw_set_camera_mode = raw_proposal.get("set_camera_mode")
            if not isinstance(raw_set_camera_mode, dict):
                return None
            raw_mode = raw_set_camera_mode.get("mode")
            if not isinstance(raw_mode, str):
                return None
            mode = self._normalize_camera_mode(raw_mode)
            if mode is None:
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                set_camera_mode=SetCameraModeParams(
                    target_device=self._normalize_target_device(
                        raw_set_camera_mode.get("target_device"), message
                    ),
                    mode=mode,
                ),
            )

        if intent == Intent.SET_LAYOUT:
            raw_set_layout = raw_proposal.get("set_layout")
            if not isinstance(raw_set_layout, dict):
                return None
            layout_name = raw_set_layout.get("layout_name")
            if not isinstance(layout_name, str) or not layout_name.strip():
                return None
            camera_mode = self._layout_name_as_camera_mode(layout_name)
            if camera_mode is not None:
                return ActionProposal(
                    intent=Intent.SET_CAMERA_MODE,
                    summary=raw_summary,
                    confidence=normalized_confidence,
                    set_camera_mode=SetCameraModeParams(
                        target_device=self._normalize_target_device(
                            raw_set_layout.get("target_device"), message
                        ),
                        mode=camera_mode,
                    ),
                )
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                set_layout=SetLayoutParams(
                    target_device=self._normalize_target_device(
                        raw_set_layout.get("target_device"), message
                    ),
                    layout_name=layout_name.strip(),
                ),
            )

        if intent == Intent.SET_PRESENTATION:
            raw_set_presentation = raw_proposal.get("set_presentation")
            if not isinstance(raw_set_presentation, dict):
                return None
            enabled = raw_set_presentation.get("enabled")
            if not isinstance(enabled, bool):
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                set_presentation=SetPresentationParams(
                    target_device=self._normalize_target_device(
                        raw_set_presentation.get("target_device"), message
                    ),
                    enabled=enabled,
                ),
            )

        if intent == Intent.SWITCH_INPUT_SOURCE:
            raw_switch_input_source = raw_proposal.get("switch_input_source")
            if not isinstance(raw_switch_input_source, dict):
                return None
            source_id = raw_switch_input_source.get("source_id")
            if not isinstance(source_id, str) or not source_id.strip():
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                switch_input_source=SwitchInputSourceParams(
                    target_device=self._normalize_target_device(
                        raw_switch_input_source.get("target_device"), message
                    ),
                    source_id=source_id.strip(),
                ),
            )

        if intent == Intent.ASSIGN_MATRIX:
            raw_assign_matrix = raw_proposal.get("assign_matrix")
            if not isinstance(raw_assign_matrix, dict):
                return None
            output = raw_assign_matrix.get("output")
            mode = raw_assign_matrix.get("mode")
            layout = raw_assign_matrix.get("layout")
            source_id = raw_assign_matrix.get("source_id")
            remote_main = raw_assign_matrix.get("remote_main")
            if (
                not isinstance(output, str)
                or not output.strip()
                or not isinstance(mode, str)
                or not mode.strip()
                or not isinstance(layout, str)
                or not layout.strip()
            ):
                return None
            if source_id is not None and (
                not isinstance(source_id, str) or not source_id.strip()
            ):
                return None
            if remote_main is not None and not isinstance(remote_main, bool):
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                assign_matrix=AssignMatrixParams(
                    target_device=self._normalize_target_device(
                        raw_assign_matrix.get("target_device"), message
                    ),
                    output=output.strip(),
                    mode=mode.strip(),
                    layout=layout.strip(),
                    source_id=source_id.strip() if isinstance(source_id, str) else None,
                    remote_main=remote_main,
                ),
            )

        if intent == Intent.UNASSIGN_MATRIX:
            raw_unassign_matrix = raw_proposal.get("unassign_matrix")
            if not isinstance(raw_unassign_matrix, dict):
                return None
            output = raw_unassign_matrix.get("output")
            source_id = raw_unassign_matrix.get("source_id")
            remote_main = raw_unassign_matrix.get("remote_main")
            if not isinstance(output, str) or not output.strip():
                return None
            if source_id is not None and (
                not isinstance(source_id, str) or not source_id.strip()
            ):
                return None
            if remote_main is not None and not isinstance(remote_main, bool):
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                unassign_matrix=UnassignMatrixParams(
                    target_device=self._normalize_target_device(
                        raw_unassign_matrix.get("target_device"), message
                    ),
                    output=output.strip(),
                    source_id=source_id.strip() if isinstance(source_id, str) else None,
                    remote_main=remote_main,
                ),
            )

        if intent == Intent.SWAP_MATRIX:
            raw_swap_matrix = raw_proposal.get("swap_matrix")
            if not isinstance(raw_swap_matrix, dict):
                return None
            output_a = raw_swap_matrix.get("output_a")
            output_b = raw_swap_matrix.get("output_b")
            if (
                not isinstance(output_a, str)
                or not output_a.strip()
                or not isinstance(output_b, str)
                or not output_b.strip()
            ):
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                swap_matrix=SwapMatrixParams(
                    target_device=self._normalize_target_device(
                        raw_swap_matrix.get("target_device"), message
                    ),
                    output_a=output_a.strip(),
                    output_b=output_b.strip(),
                ),
            )

        if intent == Intent.SET_DISPLAY_MODE:
            raw_set_display_mode = raw_proposal.get("set_display_mode")
            if not isinstance(raw_set_display_mode, dict):
                return None
            raw_mode = raw_set_display_mode.get("mode")
            if not isinstance(raw_mode, str):
                return None
            mode = self._normalize_display_mode(raw_mode)
            if mode is None:
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                set_display_mode=SetDisplayModeParams(
                    target_device=self._normalize_target_device(
                        raw_set_display_mode.get("target_device"), message
                    ),
                    mode=mode,
                ),
            )

        if intent == Intent.SET_DISPLAY_ROLE:
            raw_set_display_role = raw_proposal.get("set_display_role")
            if not isinstance(raw_set_display_role, dict):
                return None
            raw_connector_id = raw_set_display_role.get("connector_id")
            raw_role = raw_set_display_role.get("role")
            if not isinstance(raw_connector_id, int) or not isinstance(raw_role, str):
                return None
            try:
                role = DisplayRole(raw_role)
            except ValueError:
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                set_display_role=SetDisplayRoleParams(
                    target_device=self._normalize_target_device(
                        raw_set_display_role.get("target_device"), message
                    ),
                    connector_id=raw_connector_id,
                    role=role,
                ),
            )

        if intent == Intent.ACTIVATE_CAMERA_PRESET:
            raw_activate_camera_preset = raw_proposal.get("activate_camera_preset")
            if not isinstance(raw_activate_camera_preset, dict):
                return None
            preset_id = raw_activate_camera_preset.get("preset_id")
            if not isinstance(preset_id, str) or not preset_id.strip():
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                activate_camera_preset=ActivateCameraPresetParams(
                    target_device=self._normalize_target_device(
                        raw_activate_camera_preset.get("target_device"), message
                    ),
                    preset_id=preset_id.strip(),
                ),
            )

        if intent == Intent.ADJUST_CAMERA_POSITION:
            raw_adjust_camera_position = raw_proposal.get("adjust_camera_position")
            if not isinstance(raw_adjust_camera_position, dict):
                return None
            camera_id = raw_adjust_camera_position.get("camera_id")
            if not isinstance(camera_id, str) or not camera_id.strip():
                return None
            normalized_camera_id = camera_id.strip()
            if not normalized_camera_id.isdigit() or int(normalized_camera_id) <= 0:
                return None
            raw_pan = raw_adjust_camera_position.get("pan")
            raw_tilt = raw_adjust_camera_position.get("tilt")
            raw_zoom = raw_adjust_camera_position.get("zoom")
            pan = int(raw_pan) if isinstance(raw_pan, int) else None
            tilt = int(raw_tilt) if isinstance(raw_tilt, int) else None
            zoom = int(raw_zoom) if isinstance(raw_zoom, int) else None
            if pan is None and tilt is None and zoom is None:
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                adjust_camera_position=AdjustCameraPositionParams(
                    target_device=self._normalize_target_device(
                        raw_adjust_camera_position.get("target_device"), message
                    ),
                    camera_id=normalized_camera_id,
                    pan=pan,
                    tilt=tilt,
                    zoom=zoom,
                ),
            )

        if intent == Intent.SET_SPEAKERTRACK:
            raw_set_speakertrack = raw_proposal.get("set_speakertrack")
            if not isinstance(raw_set_speakertrack, dict):
                return None
            enabled = raw_set_speakertrack.get("enabled")
            if not isinstance(enabled, bool):
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                set_speakertrack=SetSpeakerTrackParams(
                    target_device=self._normalize_target_device(
                        raw_set_speakertrack.get("target_device"), message
                    ),
                    enabled=enabled,
                ),
            )

        if intent == Intent.SET_STANDBY:
            raw_set_standby = raw_proposal.get("set_standby")
            if not isinstance(raw_set_standby, dict):
                return None
            enabled = raw_set_standby.get("enabled")
            if not isinstance(enabled, bool):
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                set_standby=SetStandbyParams(
                    target_device=self._normalize_target_device(
                        raw_set_standby.get("target_device"), message
                    ),
                    enabled=enabled,
                ),
            )

        if intent == Intent.REBOOT:
            raw_reboot = raw_proposal.get("reboot")
            if not isinstance(raw_reboot, dict):
                return None
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                reboot=RebootParams(
                    target_device=self._normalize_target_device(
                        raw_reboot.get("target_device"), message
                    )
                ),
            )

        if intent == Intent.FACTORY_RESET:
            raw_factory_reset = raw_proposal.get("factory_reset")
            if not isinstance(raw_factory_reset, dict):
                return None
            acknowledged = raw_factory_reset.get("acknowledged", False)
            return ActionProposal(
                intent=intent,
                summary=raw_summary,
                confidence=normalized_confidence,
                factory_reset=FactoryResetParams(
                    target_device=self._normalize_target_device(
                        raw_factory_reset.get("target_device"), message
                    ),
                    acknowledged=(
                        acknowledged if isinstance(acknowledged, bool) else False
                    ),
                ),
            )

        return None

    def _normalize_action_payload(
        self, raw_proposal: dict[str, object]
    ) -> dict[str, object] | None:
        raw_intent = raw_proposal.get("intent")
        if not isinstance(raw_intent, str):
            return None

        intent_specific_key = {
            Intent.GET_STATUS.value: "get_status",
            Intent.GET_ENVIRONMENT_INFO.value: "get_environment_info",
            Intent.GET_CAMERA_MODE.value: "get_camera_mode",
            Intent.GET_ROOM_BOOKING.value: "get_room_booking",
            Intent.LIST_DEVICES.value: "list_devices",
            Intent.WEBEX_JOIN.value: "webex_join",
            Intent.JOIN_OBTP.value: "join_obtp",
            Intent.DIAL.value: "dial",
            Intent.HANG_UP.value: "hang_up",
            Intent.SEND_DTMF.value: "send_dtmf",
            Intent.SET_MICROPHONE_MUTE.value: "set_microphone_mute",
            Intent.SET_MICROPHONE_MODE.value: "set_microphone_mode",
            Intent.SET_VOLUME.value: "set_volume",
            Intent.SET_VIDEO_MUTE.value: "set_video_mute",
            Intent.SET_SELFVIEW.value: "set_selfview",
            Intent.SET_CAMERA_MODE.value: "set_camera_mode",
            Intent.SET_LAYOUT.value: "set_layout",
            Intent.SET_PRESENTATION.value: "set_presentation",
            Intent.SWITCH_INPUT_SOURCE.value: "switch_input_source",
            Intent.ASSIGN_MATRIX.value: "assign_matrix",
            Intent.UNASSIGN_MATRIX.value: "unassign_matrix",
            Intent.SWAP_MATRIX.value: "swap_matrix",
            Intent.SET_DISPLAY_MODE.value: "set_display_mode",
            Intent.SET_DISPLAY_ROLE.value: "set_display_role",
            Intent.ACTIVATE_CAMERA_PRESET.value: "activate_camera_preset",
            Intent.ADJUST_CAMERA_POSITION.value: "adjust_camera_position",
            Intent.SET_SPEAKERTRACK.value: "set_speakertrack",
            Intent.SET_STANDBY.value: "set_standby",
            Intent.REBOOT.value: "reboot",
            Intent.FACTORY_RESET.value: "factory_reset",
            Intent.CHAT.value: None,
            Intent.RESET_CONTEXT.value: None,
        }.get(raw_intent)

        if intent_specific_key is None:
            return raw_proposal
        if intent_specific_key in raw_proposal:
            return raw_proposal

        summary = raw_proposal.get("summary")
        confidence = raw_proposal.get("confidence")
        target_device = raw_proposal.get("target_device")

        normalized: dict[str, object] = {
            "intent": raw_intent,
            "summary": summary,
        }
        if confidence is not None:
            normalized["confidence"] = confidence

        nested_payload: dict[str, object] = {}
        if isinstance(target_device, str) and target_device.strip():
            nested_payload["target_device"] = target_device.strip()

        field_map: dict[str, tuple[str, ...]] = {
            "get_status": ("target_device", "include_metrics"),
            "get_environment_info": ("target_device",),
            "get_camera_mode": ("target_device",),
            "get_room_booking": ("target_device",),
            "list_devices": ("limit", "online_only"),
            "webex_join": ("target_device", "meeting_identifier"),
            "join_obtp": ("target_device",),
            "dial": ("target_device", "address"),
            "hang_up": ("target_device", "call_id"),
            "send_dtmf": ("target_device", "tones", "call_id"),
            "set_microphone_mute": ("target_device", "muted"),
            "set_microphone_mode": ("target_device", "mode"),
            "set_volume": ("target_device", "level"),
            "set_video_mute": ("target_device", "muted"),
            "set_selfview": ("target_device", "enabled"),
            "set_camera_mode": ("target_device", "mode"),
            "set_layout": ("target_device", "layout_name"),
            "set_presentation": ("target_device", "enabled"),
            "switch_input_source": ("target_device", "source_id"),
            "assign_matrix": (
                "target_device",
                "output",
                "mode",
                "layout",
                "source_id",
                "remote_main",
            ),
            "unassign_matrix": (
                "target_device",
                "output",
                "source_id",
                "remote_main",
            ),
            "swap_matrix": ("target_device", "output_a", "output_b"),
            "set_display_mode": ("target_device", "mode"),
            "set_display_role": ("target_device", "connector_id", "role"),
            "activate_camera_preset": ("target_device", "preset_id"),
            "adjust_camera_position": (
                "target_device",
                "camera_id",
                "pan",
                "tilt",
                "zoom",
            ),
            "set_speakertrack": ("target_device", "enabled"),
            "set_standby": ("target_device", "enabled"),
            "reboot": ("target_device",),
            "factory_reset": ("target_device", "acknowledged"),
        }
        for field_name in field_map.get(intent_specific_key, ()):
            value = raw_proposal.get(field_name)
            if value is not None:
                nested_payload[field_name] = value

        normalized[intent_specific_key] = nested_payload
        return normalized

    def _normalize_display_mode(self, raw_mode: str) -> DisplayMode | None:
        normalized = raw_mode.strip().casefold()
        aliases = {
            "left-video-right-video": DisplayMode.LEFT_VIDEO_RIGHT_VIDEO,
            "left video right video": DisplayMode.LEFT_VIDEO_RIGHT_VIDEO,
            "왼쪽영상오른쪽영상": DisplayMode.LEFT_VIDEO_RIGHT_VIDEO,
            "dual": DisplayMode.LEFT_VIDEO_RIGHT_VIDEO,
            "left-video-right-presentation": DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
            "left video right presentation": DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
            "왼쪽영상오른쪽프리젠테이션": DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
            "왼쪽영상오른쪽프레젠테이션": DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
            "dual-presentation-only": DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
            "dual presentation only": DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
            "dual presentation-only": DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
            "dual-presentation only": DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
            "dualpresentationonly": DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
            "left-presentation-right-video": DisplayMode.LEFT_PRESENTATION_RIGHT_VIDEO,
            "left presentation right video": DisplayMode.LEFT_PRESENTATION_RIGHT_VIDEO,
            "왼쪽프리젠테이션오른쪽영상": DisplayMode.LEFT_PRESENTATION_RIGHT_VIDEO,
            "왼쪽프레젠테이션오른쪽영상": DisplayMode.LEFT_PRESENTATION_RIGHT_VIDEO,
            "both-presentation": DisplayMode.BOTH_PRESENTATION,
            "both presentation": DisplayMode.BOTH_PRESENTATION,
            "양쪽모두프리젠테이션": DisplayMode.BOTH_PRESENTATION,
            "양쪽모두프레젠테이션": DisplayMode.BOTH_PRESENTATION,
        }
        return aliases.get(normalized)

    def _layout_name_as_camera_mode(self, layout_name: str) -> WritableCameraMode | None:
        normalized = " ".join(layout_name.strip().lower().replace("_", " ").split())
        return self.CAMERA_MODE_LAYOUT_ALIASES.get(normalized)

    def _normalize_target_device(
        self, raw_target_device: object, message: InboundUserMessage
    ) -> str:
        mentioned_target_device = (
            self._fallback_provider._extract_mentioned_target_device(
                message.text,
                message.target_device,
            )
        )
        normalized_raw_target_device = (
            raw_target_device.strip() if isinstance(raw_target_device, str) else None
        )

        if isinstance(mentioned_target_device, str) and mentioned_target_device.strip():
            return mentioned_target_device.strip()
        if (
            normalized_raw_target_device is not None
            and normalized_raw_target_device
            and normalized_raw_target_device != self.default_target_device
        ):
            return normalized_raw_target_device
        if (
            normalized_raw_target_device is not None
            and normalized_raw_target_device
            and not self.default_target_device
        ):
            return normalized_raw_target_device
        return ""

    def _normalize_camera_mode(self, raw_mode: str) -> WritableCameraMode | None:
        normalized = " ".join(raw_mode.strip().casefold().replace("_", " ").split())
        direct_map = {
            "auto": WritableCameraMode.AUTO,
            "enable": WritableCameraMode.AUTO,
            "enabled": WritableCameraMode.AUTO,
            "off": WritableCameraMode.OFF,
            "disable": WritableCameraMode.OFF,
            "disabled": WritableCameraMode.OFF,
        }
        mode = direct_map.get(normalized)
        if mode is not None:
            return mode
        compact = normalized.replace(" ", "")
        return direct_map.get(compact)

    def _normalize_meeting_identifier(
        self, raw_meeting_identifier: object
    ) -> str | None:
        if not isinstance(raw_meeting_identifier, str):
            return None
        meeting_identifier = raw_meeting_identifier.strip()
        if not meeting_identifier:
            return None
        return meeting_identifier

    def _looks_like_internal_meeting_identifier(
        self,
        meeting_identifier: str,
        message: InboundUserMessage,
    ) -> bool:
        normalized_identifier = meeting_identifier.strip()
        lowered_identifier = normalized_identifier.lower()
        if not lowered_identifier:
            return True

        internal_candidates = {
            value.strip()
            for value in (message.session_id, message.room_id)
            if isinstance(value, str) and value.strip()
        }
        if normalized_identifier in internal_candidates:
            return True

        if lowered_identifier.startswith(("ciscospark://", "cizyccosporak://")):
            return True
        if "/room/" in lowered_identifier:
            return True
        if "/people/" in lowered_identifier or "/message/" in lowered_identifier:
            return True
        if (
            "/webhook/" in lowered_identifier
            or "/attachment_action/" in lowered_identifier
        ):
            return True
        if "/" in normalized_identifier:
            return True

        decoded_candidate = self._try_decode_webex_identifier(normalized_identifier)
        if decoded_candidate is not None:
            lowered_decoded = decoded_candidate.lower()
            if lowered_decoded.startswith("ciscospark://"):
                return True
            if "/room/" in lowered_decoded:
                return True

        return False

    def _try_decode_webex_identifier(self, value: str) -> str | None:
        if not value or any(character.isspace() for character in value):
            return None
        padded = value + ("=" * (-len(value) % 4))
        try:
            decoded = b64decode(padded, validate=True).decode("utf-8")
        except Exception:
            return None
        return decoded

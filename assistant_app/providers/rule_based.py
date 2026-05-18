from __future__ import annotations

import re

from assistant_app.providers import rule_based_extractors as _rbx
from assistant_app.providers.rule_based_extractors import (
    CameraPositionMatch,
    MatrixAssignMatch,
    MatrixSwapMatch,
    MatrixUnassignMatch,
)
from assistant_app.providers.rule_based_handlers import audio as _audio_handler
from assistant_app.providers.rule_based_handlers import booking as _booking_handler
from assistant_app.providers.rule_based_handlers import camera as _camera_handler
from assistant_app.providers.rule_based_handlers import matrix as _matrix_handler
from assistant_app.providers.rule_based_handlers import meeting as _meeting_handler
from assistant_app.providers.rule_based_handlers import system as _system_handler
from assistant_app.providers.rule_based_handlers import video as _video_handler
from assistant_app.tracing import traced
from shared.contracts import (
    ActionProposal,
    DisplayMode,
    DisplayRole,
    ExecutionResult,
    GetStatusParams,
    InboundUserMessage,
    Intent,
    MicrophoneProcessingMode,
    OrchestrationDecision,
    ProviderSettings,
    SessionContext,
    SetPresentationParams,
    SetSpeakerTrackParams,
    SetStandbyParams,
    WritableCameraMode,
)


class RuleBasedProvider:
    SOURCE_ALIAS_PATTERN: re.Pattern[str] = re.compile(
        r"(?:switch\s+)?(?:input\s+source|source\s+input)\s+(?:to\s+)?([A-Za-z0-9_-]+)",
        re.IGNORECASE,
    )
    PROMINENT_LAYOUT_PHRASES: tuple[str, ...] = (
        "layout prominent",
        "prominent layout",
        "make layout prominent",
        "set layout prominent",
        "set layout to prominent",
        "switch layout to prominent",
    )
    TOGGLE_ACTION_NAMES: frozenset[str] = frozenset(
        {
            "selfview",
            "self view",
            "speakertrack",
            "speaker track",
            "standby",
            "presentation",
            "share",
            "video",
            "camera",
        }
    )
    CAMERA_PAN_STEP: int = 1000
    CAMERA_TILT_STEP: int = 1000
    CAMERA_ZOOM_STEP: int = 700

    def __init__(self, default_target_device: str) -> None:
        self.default_target_device: str = default_target_device
        self.settings: ProviderSettings = ProviderSettings()

    def bind_settings(self, settings: ProviderSettings) -> None:
        self.settings = settings

    async def render_execution_reply(
        self,
        execution_result: ExecutionResult,
        policy_reason: str,
        canonical_text: str,
    ) -> str | None:
        _ = execution_result
        _ = policy_reason
        _ = canonical_text
        return None

    @traced("provider.analyze_message")
    async def analyze_message(
        self,
        message: InboundUserMessage,
        session: SessionContext,
    ) -> OrchestrationDecision:
        text = message.text.strip()
        lowered = text.lower()

        if lowered in {"admin login", "admin auth", "/admin-login"}:
            return OrchestrationDecision(
                reply_text="I started an admin login approval request.",
                action_proposal=ActionProposal(
                    intent=Intent.CHAT,
                    summary="Start admin login approval.",
                ),
            )

        target_device = self._extract_target_device(text, message.target_device)
        mentioned_target_device = self._extract_mentioned_target_device(text, message.target_device)

        early_decision = _system_handler.handle_early(
            text=text,
            lowered=lowered,
            target_device=target_device,
            mentioned_target_device=mentioned_target_device,
            session=session,
            provider=self,
        )
        if early_decision is not None:
            return early_decision

        booking_decision = _booking_handler.handle(
            text=text,
            lowered=lowered,
            target_device=target_device,
            mentioned_target_device=mentioned_target_device,
            session=session,
            provider=self,
        )
        if booking_decision is not None:
            return booking_decision

        if "status" in lowered:
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.GET_STATUS,
                    summary="Get the current device status.",
                    get_status=GetStatusParams(target_device=target_device),
                )
            )

        camera_get_decision = _camera_handler.handle_get_mode(
            text=text,
            lowered=lowered,
            target_device=target_device,
            mentioned_target_device=mentioned_target_device,
            session=session,
            provider=self,
        )
        if camera_get_decision is not None:
            return camera_get_decision

        meeting_decision = _meeting_handler.handle(
            text=text,
            lowered=lowered,
            target_device=target_device,
            mentioned_target_device=mentioned_target_device,
            message_target_device=message.target_device,
            session=session,
            provider=self,
        )
        if meeting_decision is not None:
            return meeting_decision

        audio_decision = _audio_handler.handle(
            text=text,
            lowered=lowered,
            target_device=target_device,
            mentioned_target_device=mentioned_target_device,
            session=session,
            provider=self,
        )
        if audio_decision is not None:
            return audio_decision

        video_mute_decision = _video_handler.handle_video_mute(
            text=text,
            lowered=lowered,
            target_device=target_device,
            mentioned_target_device=mentioned_target_device,
            session=session,
            provider=self,
        )
        if video_mute_decision is not None:
            return video_mute_decision

        camera_set_decision = _camera_handler.handle_set_mode_and_selfview(
            text=text,
            lowered=lowered,
            target_device=target_device,
            mentioned_target_device=mentioned_target_device,
            message_target_device=message.target_device,
            session=session,
            provider=self,
        )
        if camera_set_decision is not None:
            return camera_set_decision

        if "presentation" in lowered or "share" in lowered:
            enabled = self._extract_toggle_state(
                lowered,
                enable_words={
                    "start presentation",
                    "presentation start",
                    "start share",
                    "turn on presentation",
                    "turn on share",
                },
                disable_words={
                    "stop presentation",
                    "presentation stop",
                    "stop share",
                    "turn off presentation",
                    "turn off share",
                },
            )
            if enabled is not None:
                return OrchestrationDecision(
                    action_proposal=ActionProposal(
                        intent=Intent.SET_PRESENTATION,
                        summary="Start or stop presentation.",
                        set_presentation=SetPresentationParams(
                            target_device=target_device,
                            enabled=enabled,
                        ),
                    )
                )

        matrix_decision = _matrix_handler.handle(
            text=text,
            lowered=lowered,
            target_device=target_device,
            mentioned_target_device=mentioned_target_device,
            session=session,
            provider=self,
        )
        if matrix_decision is not None:
            return matrix_decision

        video_late_decision = _video_handler.handle_layout_and_display(
            text=text,
            lowered=lowered,
            target_device=target_device,
            mentioned_target_device=mentioned_target_device,
            session=session,
            provider=self,
        )
        if video_late_decision is not None:
            return video_late_decision

        camera_late_decision = _camera_handler.handle_position_and_preset(
            text=text,
            lowered=lowered,
            target_device=target_device,
            mentioned_target_device=mentioned_target_device,
            session=session,
            provider=self,
        )
        if camera_late_decision is not None:
            return camera_late_decision

        if "speakertrack" in lowered or "speaker track" in lowered:
            enabled = self._extract_toggle_state(
                lowered,
                enable_words={
                    "speakertrack on",
                    "activate speakertrack",
                    "speaker track on",
                    "turn on speakertrack",
                    "turn on speaker track",
                },
                disable_words={
                    "speakertrack off",
                    "deactivate speakertrack",
                    "speaker track off",
                    "turn off speakertrack",
                    "turn off speaker track",
                },
            )
            if enabled is not None:
                return OrchestrationDecision(
                    action_proposal=ActionProposal(
                        intent=Intent.SET_SPEAKERTRACK,
                        summary="Change SpeakerTrack state.",
                        set_speakertrack=SetSpeakerTrackParams(
                            target_device=target_device,
                            enabled=enabled,
                        ),
                    )
                )

        if "standby" in lowered:
            enabled = self._extract_toggle_state(
                lowered,
                enable_words={
                    "standby on",
                    "activate standby",
                    "enter standby",
                    "turn on standby",
                },
                disable_words={
                    "standby off",
                    "deactivate standby",
                    "exit standby",
                    "turn off standby",
                },
            )
            if enabled is not None:
                return OrchestrationDecision(
                    action_proposal=ActionProposal(
                        intent=Intent.SET_STANDBY,
                        summary="Change standby state.",
                        set_standby=SetStandbyParams(
                            target_device=target_device,
                            enabled=enabled,
                        ),
                    )
                )

        late_system_decision = _system_handler.handle_late(
            text=text,
            lowered=lowered,
            target_device=target_device,
            mentioned_target_device=mentioned_target_device,
            session=session,
            provider=self,
        )
        if late_system_decision is not None:
            return late_system_decision

        fallback = (
            "I can currently help with read-only device status. "
            "Try 'get status of RoomKit-7F' or '/reset'."
        )
        if session.last_intent == Intent.GET_STATUS:
            fallback = "I only support the get_status flow in this MVP. Try another device status query or '/reset'."

        return OrchestrationDecision(reply_text=fallback)

    def _is_list_devices_request(self, lowered_text: str) -> bool:
        return _rbx.is_list_devices_request(lowered_text)

    def _is_get_camera_mode_request(self, lowered_text: str) -> bool:
        return _rbx.is_get_camera_mode_request(lowered_text)

    def _is_get_environment_info_request(self, lowered_text: str) -> bool:
        return _rbx.is_get_environment_info_request(lowered_text)

    def _is_get_room_booking_request(self, lowered_text: str) -> bool:
        return _rbx.is_get_room_booking_request(lowered_text)

    def _is_webex_join_request(self, lowered_text: str) -> bool:
        return _rbx.is_webex_join_request(lowered_text)

    def _is_join_obtp_request(self, lowered_text: str) -> bool:
        return _rbx.is_join_obtp_request(lowered_text)

    def _is_set_camera_mode_request(self, lowered_text: str) -> bool:
        return _rbx.is_set_camera_mode_request(lowered_text)

    def _mentions_camera_mode(self, lowered_text: str) -> bool:
        return _rbx.mentions_camera_mode(lowered_text)

    def _extract_target_device(self, text: str, explicit_target: str | None) -> str:
        return _rbx.extract_target_device(text, explicit_target, self.default_target_device)

    def _extract_mentioned_target_device(
        self, text: str, explicit_target: str | None
    ) -> str | None:
        return _rbx.extract_mentioned_target_device(text, explicit_target)

    def _extract_trailing_target_device(self, text: str) -> str | None:
        return _rbx.extract_trailing_target_device(text)

    def _extract_turn_toggle_target_device(self, text: str) -> str | None:
        return _rbx.extract_turn_toggle_target_device(text)

    def _strip_trailing_target_clause(self, text: str) -> str:
        return _rbx.strip_trailing_target_clause(text)

    def _extract_korean_phrase_target_device(self, text: str) -> str | None:
        return _rbx.extract_korean_phrase_target_device(text)

    def _extract_volume_level(self, text: str) -> int | None:
        return _rbx.extract_volume_level(text)

    def _extract_webex_meeting_identifier(self, text: str) -> str | None:
        return _rbx.extract_webex_meeting_identifier(text)

    def _extract_dial_address(self, text: str) -> str | None:
        return _rbx.extract_dial_address(text)

    def _extract_dtmf_tones(self, text: str) -> str | None:
        return _rbx.extract_dtmf_tones(text)

    def _extract_call_id(self, text: str) -> int | None:
        return _rbx.extract_call_id(text)

    def _mentions_microphone_toggle(self, lowered_text: str) -> bool:
        return _rbx.mentions_microphone_toggle(lowered_text)

    def _mentions_video_toggle(self, lowered_text: str) -> bool:
        return _rbx.mentions_video_toggle(lowered_text)

    def _extract_camera_mode(self, lowered_text: str) -> WritableCameraMode | None:
        return _rbx.extract_camera_mode(lowered_text)

    def _extract_toggle_state(
        self,
        lowered_text: str,
        enable_words: set[str],
        disable_words: set[str],
        enable_value: bool = True,
    ) -> bool | None:
        return _rbx.extract_toggle_state(lowered_text, enable_words, disable_words, enable_value)

    def _extract_layout_name(self, text: str) -> str | None:
        return _rbx.extract_layout_name(text)

    def _extract_source_id(self, text: str) -> str | None:
        return _rbx.extract_source_id(text)

    def _extract_matrix_assign(self, text: str) -> MatrixAssignMatch | None:
        return _rbx.extract_matrix_assign(text)

    def _extract_matrix_unassign(self, text: str) -> MatrixUnassignMatch | None:
        return _rbx.extract_matrix_unassign(text)

    def _extract_matrix_swap(self, text: str) -> MatrixSwapMatch | None:
        return _rbx.extract_matrix_swap(text)

    def _extract_preset_id(self, text: str) -> str | None:
        return _rbx.extract_preset_id(text)

    def _extract_camera_position(self, text: str) -> CameraPositionMatch | None:
        return _rbx.extract_camera_position(text)

    def _extract_microphone_mode(self, lowered_text: str) -> MicrophoneProcessingMode | None:
        return _rbx.extract_microphone_mode(lowered_text)

    def _extract_display_mode(self, lowered_text: str) -> DisplayMode | None:
        return _rbx.extract_display_mode(lowered_text)

    def _extract_display_role(self, lowered_text: str) -> DisplayRole | None:
        return _rbx.extract_display_role(lowered_text)

    def _extract_connector_id(self, text: str) -> int | None:
        return _rbx.extract_connector_id(text)

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from urllib.parse import quote

import websockets

from .session_store import PersistentSession
from .token_store import decode_jwt_payload, is_substrate_token_claims

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - zoneinfo is stdlib on 3.9+
    ZoneInfo = None


def _resolve_timezone(name: str) -> tuple[str, int]:
    """Return (timezone_name, utc_offset_hours) for the substrate locationInfo.

    Copilot uses the offset to render times (e.g. meeting start times). The offset
    must match the user's zone, not a hardcoded value. When ``name`` is a valid IANA
    zone we derive its current offset (honoring DST); otherwise we fall back to the
    machine's local zone so times are still correct out of the box.
    """
    def _hours(offset) -> int:
        return int(offset.total_seconds() // 3600) if offset else 0

    local = datetime.now().astimezone()
    local_offset = _hours(local.utcoffset())
    if name:
        if ZoneInfo is not None:
            try:
                return name, _hours(datetime.now(ZoneInfo(name)).utcoffset())
            except Exception:
                pass
        # Named but unresolvable (e.g. no tz database): keep the name for display,
        # use the machine's local offset for the math.
        return name, local_offset
    # Unset: synthesize a valid, recognized fixed-offset zone for the local offset.
    # The machine's display name (e.g. "Eastern Daylight Time") is NOT a recognized
    # zone id and makes the substrate return empty responses, so never send it.
    return _fixed_offset_zone(local_offset), local_offset


def _fixed_offset_zone(offset_hours: int) -> str:
    """A recognized IANA zone id for a whole-hour UTC offset.

    IANA's Etc/GMT zones use an inverted sign (Etc/GMT+4 == UTC-4).
    """
    if offset_hours == 0:
        return "UTC"
    sign = "+" if offset_hours < 0 else "-"
    return f"Etc/GMT{sign}{abs(offset_hours)}"

SIGNALR_SEP = "\x1e"
_WS_BASE = "wss://substrate.office.com/m365Copilot/Chathub"

_VARIANTS = (
    "EnableMcpServerWidgets,feature.EnableMcpServerWidgets,feature.EnableLuForChatCIQ,"
    "feature.enableChatCIQPlugin,EnableRequestPlugins,feature.EnableSensitivityLabels,"
    "EnableUnsupportedUrlDetector,feature.IsCustomEngineCopilotEnabled,feature.bizchatfluxv3,"
    "feature.enablechatpages,feature.enableCodeCanvas,feature.turnOnWorkTabRecommendation,"
    "feature.turnOnDARecommendation,feature.IsStreamingModeInChatRequestEnabled,"
    "IncludeSourceAttributionsConcise,SkipPublishEmptyMessage,"
    "feature.EnableDeduplicatingSourceAttributions,Enable3PActionProgressMessages,"
    "feature.enableClientWebRtc,feature.EnableMeetingRecapOfSeriesMeetingWithCiq,"
    "feature.EnableReferencesListCompleteSignal,feature.StorageMessageSplitDisabled,"
    "feature.EnableCuaTakeControlApi,SingletonEnvOn,feature.cwcallowedos,"
    "feature.EnableMergingPureDeltas,feature.disabledisallowedmsgs,"
    "feature.enableCitationsForSynthesisData,feature.EnableConversationShareApis,"
    "feature.enableGenerateGraphicArtOptionsSet,cdximagen,"
    "feature.EnableUpdatedUXForConfirmationDialog,"
    "feature.EnableContentApiandDocTypeHtmlInRichAnswers,"
    "cdxgrounding_api_v2_rich_web_answers_reference_bottom_force,"
    "cdxenablerenderforisocomp,feature.EnableClientFileURLSupportForOfficeWebPaidCopilot,"
    "feature.EnableDesignEditorImageGrounding,feature.EnableDesignerEditor,"
    "feature.EnableSkipRehydrationForSpeCIdImages,feature.EnableSkipEmittingMessageOnFlush,"
    "feature.EnableRemoveEmptySourceAttributions,feature.EnableRemoveStreamingMode,"
    "feature.OfficeWebToHelix,feature.OfficeDesktopToHelix,feature.M365TeamsHubToHelix,"
    "feature.OwaHubToHelix,feature.MonarchHubToHelix,feature.Win32OutlookHubToHelix,"
    "feature.MacOutlookHubToHelix,Agt_bizchat_enableGpt5ForHelix"
)

_OPTIONS_SETS = [
    "search_result_progress_messages_with_search_queries",
    "cwc_flux_image",
    "cwc_code_interpreter",
    "cwc_code_interpreter_amsfix",
    "cwcfluxgptv",
    "flux_v3_gptv_enable_upload_multi_image_in_turn_wo_ch",
    "cwc_code_interpreter_citation_fix",
    "code_interpreter_interactive_charts",
    "cwc_code_interpreter_interactive_charts_inline_image",
    "code_interpreter_matplotlib_patching",
    "cwc_fileupload_odb",
    "update_memory_plugin",
    "add_custom_instructions",
    "cwc_flux_v3",
    "flux_v3_progress_messages",
    "enable_batch_token_processing",
    "enable_gg_gpt",
    "flux_v3_image_gen_enable_dimensions",
    "flux_v3_image_gen_enable_icon_dimensions",
    "flux_v3_image_gen_enable_system_text_with_params",
    "flux_v3_image_gen_enable_designer_dimensions_meta_prompting_in_system_prompts",
]

# Enterprise "Work" option-sets captured from the real M365 Copilot web UI with
# Work IQ enabled. bizchat_enable_federated_connectors and the enterprise_* flags
# are what let Copilot ground answers in the user's Microsoft 365 (Graph) data.
_WORK_OPTIONS_SETS = [
    "at_mention_plugins_enable",
    "enable_confirmation_interstitial",
    "enable_plugin_auth_interstitial",
    "enable_request_response_interstitials",
    "enable_response_action_processing",
    "enterprise_flux_image",
    "enterprise_flux_web",
    "enterprise_flux_work",
    "enterprise_toolbox_with_skdsstore",
    "enterprise_pagination_support",
    "search_result_progress_messages_with_search_queries",
    "flux_v3_gptv_enable_upload_multi_image_in_turn_wo_ch",
    "rich_responses",
    "gptvnorm2048",
    "enterprise_flux_work_code_interpreter",
    "cwc_code_interpreter_citation_fix",
    "code_interpreter_interactive_charts",
    "enterprise_code_interpreter_citation_fix",
    "cwc_code_interpreter_interactive_charts_inline_image",
    "code_interpreter_matplotlib_patching",
    "enable_batch_token_processing",
    "disable_cea_message_listener",
    "enable_selective_url_redaction",
    "update_memory_plugin",
    "add_custom_instructions",
    "agent_recommendations",
    "enable_gg_gpt",
    "enable_inferred_memory_read",
    "update_textdoc_response_after_streaming",
    "deepleo_networking_timeout_10minutes_canmore",
    "flux_v3_image_gen_enable_dimensions",
    "flux_v3_image_gen_enable_non_watermarked_storage",
    "flux_v3_image_gen_enable_icon_dimensions",
    "flux_v3_image_gen_enable_system_text_with_params",
    "flux_v3_image_gen_enable_designer_dimensions_meta_prompting_in_system_prompts",
    "flux_v3_image_gen_enable_story",
    "bizchat_enable_federated_connectors",
]

_ALLOWED_MESSAGE_TYPES = [
    "Chat", "Suggestion", "InternalSearchQuery", "Disengaged",
    "InternalLoaderMessage", "Progress", "GeneratedCode", "RenderCardRequest",
    "AdsQuery", "SemanticSerp", "GenerateContentQuery", "GenerateGraphicArt",
    "SearchQuery", "ConfirmationCard", "AuthError", "DeveloperLogs",
    "TriggerPlugin", "HintInvocation", "MemoryUpdate", "EndOfRequest",
    "TriggerConfirmation", "ResumeInvokeAction", "ResumeUserInputRequest",
    "TriggerUserInputRequest", "EscapeHatch", "TriggerPluginAuth",
    "ResumePluginAuth", "SideBySide", "ReferencesListComplete",
    "SwitchRespondingEndpoint",
]


class SubstrateCopilotError(RuntimeError):
    pass


class SubstrateCopilotClient:
    def __init__(
        self,
        access_token: str,
        time_zone: str = "",
        work_mode: bool = True,
    ):
        if not access_token:
            raise SubstrateCopilotError(
                "M365_ACCESS_TOKEN is missing. Start the debug Edge window and let startup token capture complete, "
                "or run `uv run copilot-openai-proxy set-token`."
            )
        self._token = access_token
        self._time_zone, self._tz_offset_hours = _resolve_timezone(time_zone)
        self._work_mode = work_mode
        try:
            claims = decode_jwt_payload(access_token)
        except Exception as exc:
            raise SubstrateCopilotError(f"Cannot decode access token: {exc}") from exc
        if not is_substrate_token_claims(claims):
            raise SubstrateCopilotError("Access token is not a substrate.office.com token.")
        if time.time() > claims.get("exp", 0):
            raise SubstrateCopilotError(
                "Access token expired. To refresh: open M365 Copilot in your browser, "
                "DevTools → Network → filter 'substrate' → click the WebSocket → Headers → "
                "copy the access_token= query param → update M365_ACCESS_TOKEN in .env"
            )
        self._oid: str = claims["oid"]
        self._tid: str = claims["tid"]

    def _ws_url(self, conv_id: str, session_id: str, req_id: str) -> str:
        token = quote(self._token, safe="")
        # Work mode (agent=work, scenario=officeweb) is what lets Copilot ground in
        # the user's Microsoft 365 data; web mode is the general/web-only assistant.
        if self._work_mode:
            tail = "&licenseType=Premium&isEdu=false&agent=work&scenario=officeweb"
        else:
            tail = "&licenseType=Starter&agent=web&scenario=OfficeWebIncludedCopilot"
        return (
            f"{_WS_BASE}/{self._oid}@{self._tid}"
            f"?ClientRequestId={req_id}"
            f"&X-SessionId={session_id}"
            f"&ConversationId={conv_id}"
            f"&access_token={token}"
            f"&variants={_VARIANTS}"
            f"&source=officeweb&product=Office&agentHost=Bizchat.FullScreen"
            f"{tail}"
        )

    def _chat_invoke(
        self,
        text: str,
        conv_id: str,
        session_id: str,
        req_id: str,
        is_start_of_session: bool,
    ) -> str:
        payload = {
            "arguments": [{
                "source": "officeweb",
                "clientCorrelationId": req_id,
                "sessionId": session_id,
                "optionsSets": _WORK_OPTIONS_SETS if self._work_mode else _OPTIONS_SETS,
                "streamingMode": "ConciseWithPadding",
                "spokenTextMode": "None",
                "options": {},
                "extraExtensionParameters": {},
                "allowedMessageTypes": _ALLOWED_MESSAGE_TYPES,
                "sliceIds": [],
                "threadLevelGptId": {},
                "traceId": req_id,
                "isStartOfSession": is_start_of_session,
                "clientInfo": {
                    "clientPlatform": "mcmcopilot-web",
                    "clientAppName": "Office",
                    "clientEntrypoint": "mcmcopilot-officeweb",
                    "clientSessionId": session_id,
                    "clientAppType": "Web",
                    "deviceOS": "Windows",
                    "deviceType": "Desktop",
                },
                "message": {
                    "author": "user",
                    "inputMethod": "Keyboard",
                    "text": text,
                    "entityAnnotationTypes": ["People", "File", "Event", "Email", "TeamsMessage"],
                    "requestId": req_id,
                    "locationInfo": {"timeZoneOffset": self._tz_offset_hours, "timeZone": self._time_zone},
                    "locale": "en-us",
                    "messageType": "Chat",
                    "experienceType": "Default",
                    "adaptiveCards": [],
                    "clientPreferences": {},
                },
                "plugins": [{"Id": "BingWebSearch", "Source": "BuiltIn"}],
                "isSbsSupported": True,
                "tone": "Magic",
                "renderReferencesBehindEOS": True,
            }],
            "invocationId": "0",
            "target": "chat",
            "type": 4,
        }
        if self._work_mode:
            args = payload["arguments"][0]
            args["clientInfo"].update({
                "ProductCategory": "Chat",
                "productEntryPoint": "ChatPanel",
                "clientPlatformVersion": "10",
            })
            args["disconnectBehavior"] = "continue"
        return json.dumps(payload, ensure_ascii=False) + SIGNALR_SEP

    async def chat_stream(
        self,
        prompt: str,
        additional_context: list[str],
        session: PersistentSession | None = None,
    ) -> AsyncIterator[str]:
        text = _combine_text(prompt, additional_context)
        if session is None:
            async for chunk in self._chat_stream_for_turn(
                text=text,
                conv_id=str(uuid.uuid4()),
                session_id=str(uuid.uuid4()),
                is_start_of_session=True,
            ):
                yield chunk
            return

        async with session.lock:
            turn = session.reserve_turn()
            async for chunk in self._chat_stream_for_turn(
                text=text,
                conv_id=turn.conversation_id,
                session_id=turn.client_session_id,
                is_start_of_session=turn.is_start_of_session,
            ):
                yield chunk

    async def _chat_stream_for_turn(
        self,
        text: str,
        conv_id: str,
        session_id: str,
        is_start_of_session: bool,
    ) -> AsyncIterator[str]:
        req_id = str(uuid.uuid4())
        url = self._ws_url(conv_id, session_id, req_id)
        try:
            async with websockets.connect(
                url,
                additional_headers={
                    "Origin": "https://m365.cloud.microsoft",
                },
            ) as ws:
                await ws.send(json.dumps({"protocol": "json", "version": 1}) + SIGNALR_SEP)
                await ws.recv()
                await ws.send(self._chat_invoke(text, conv_id, session_id, req_id, is_start_of_session))
                fallback_text = ""
                yielded_any = False
                async for raw in ws:
                    for part in raw.split(SIGNALR_SEP):
                        part = part.strip()
                        if not part:
                            continue
                        try:
                            msg = json.loads(part)
                        except json.JSONDecodeError:
                            continue
                        t = msg.get("type")
                        if t == 6:
                            continue
                        if t == 1 and msg.get("target") == "update":
                            args = (msg.get("arguments") or [{}])[0]
                            delta = args.get("writeAtCursor")
                            if delta:
                                if not yielded_any and fallback_text:
                                    yield fallback_text
                                yielded_any = True
                                yield delta
                            msgs = args.get("messages")
                            if msgs:
                                entries = msgs if isinstance(msgs, list) else [msgs]
                                for entry in reversed(entries):
                                    if entry.get("author") != "user":
                                        fallback_text = entry.get("text", "")
                                        break
                        if t == 2:
                            item_msgs = (msg.get("item") or {}).get("messages") or []
                            for entry in reversed(item_msgs):
                                if entry.get("author") != "user":
                                    fallback_text = entry.get("text", "")
                                    break
                        if t == 3:
                            if not yielded_any and fallback_text:
                                yield fallback_text
                            return
        except SubstrateCopilotError:
            raise
        except Exception as exc:
            raise SubstrateCopilotError(str(exc)) from exc

    async def chat(
        self,
        prompt: str,
        additional_context: list[str],
        session: PersistentSession | None = None,
    ) -> str:
        chunks: list[str] = []
        async for chunk in self.chat_stream(prompt, additional_context, session):
            chunks.append(chunk)
        return "".join(chunks)


def _combine_text(prompt: str, context: list[str]) -> str:
    if not context:
        return prompt
    return "\n\n".join(context) + "\n\n---\n\n" + prompt

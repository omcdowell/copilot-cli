import os
import pathlib
import subprocess  # nosec
import uuid
from typing import Optional

import jwt
import requests
import websockets

from copilot_cli.common.cache.cached_entity import CachedEntity
from copilot_cli.common.cache.token_cache import TokenCache
from copilot_cli.copilot.enums.copilot_scenario_enum import CopilotScenarioEnum
from copilot_cli.copilot.enums.message_type_enum import MessageTypeEnum
from copilot_cli.copilot.enums.verbose_enum import VerboseEnum
from copilot_cli.copilot.exceptions.copilot_connected_user_mismatch import CopilotConnectedUserMismatchException
from copilot_cli.copilot.exceptions.copilot_connection_failed_exception import CopilotConnectionFailedException
from copilot_cli.copilot.exceptions.copilot_connection_not_initialized_exception import CopilotConnectionNotInitializedException
from copilot_cli.copilot.loggers.file_logger import FileLogger
from copilot_cli.copilot.models.agent_info_model import AgentInfoModel
from copilot_cli.copilot.models.chat_argument import ChatArguments
from copilot_cli.copilot.models.conversation_parameters import ConversationParameters
from copilot_cli.copilot.websocket_message.websocket_message import WebsocketMessage

TOOL_PROMPT = "[Tool]: "


class CopilotConnector:
    """
    A class that is responsible for connecting and interacting with the Copilot
    """

    _SUBSTRATE_TOKEN_CACHE_KEY = "substrate_access_token"  # nosec
    _SUBSTRATE_OID_CACHE_KEY = "substrate_oid"
    _SUBSTRATE_TID_CACHE_KEY = "substrate_tid"
    _SUBSTRATE_USER_CACHE_KEY = "substrate_user"

    def __init__(self, arguments: ChatArguments) -> None:
        self.__is_initialized = False
        self.__arguments = arguments
        self.__conversation_params: Optional[ConversationParameters] = None
        self.__index = 0
        self.__token_cache = TokenCache()
        self.__file_logger: Optional[FileLogger] = None

    def init_connection(self) -> None:
        """
        Initializes the connection with the Copilot
        """
        if self.__is_initialized:
            return

        self.__conversation_params = self.__get_conversation_parameters()
        self.__file_logger = FileLogger(f"session_{self.__conversation_params.session_id}.log")

        self.__is_initialized = True

    def refresh_connection(self) -> None:
        """
        Refresh the connection with the Copilot
        """
        self.__conversation_params = self.__get_conversation_parameters(True)
        self.__file_logger = FileLogger(f"session_{self.__conversation_params.session_id}.log")

        self.__is_initialized = True

    @property
    def conversation_parameters(self) -> ConversationParameters:
        # if connection was not initialized correctly, an exception will be raised
        self.init_connection()
        return self.__conversation_params

    async def connect(self, prompt: str) -> Optional[WebsocketMessage]:
        """
        Connects to the Copilot via a websocket and sends a prompt

        :param prompt: prompt to send

        raises CopilotConnectionNotInitializedException: when sending a prompt without initializing the connection

        returns: the response from the Copilot as a WebsocketMessage
        """
        if not self.__is_initialized:
            raise CopilotConnectionNotInitializedException("Copilot connection not initialized.")

        url = self.__conversation_params.url

        protocol_message = {"protocol": "json", "version": 1}
        ping_message = {"type": 6}

        inputs = [protocol_message, ping_message, self.__get_prompt(prompt)]

        async with websockets.connect(url) as websocket:
            for input in inputs:
                payload = WebsocketMessage.to_websocket_message(input)
                websocket_payload = WebsocketMessage(payload)
                self.__log(websocket_payload)
                is_user_input = websocket_payload.type() == MessageTypeEnum.user
                await websocket.send(payload)
                stop_polling = False
                while not stop_polling:
                    response = await websocket.recv()
                    websocket_message = WebsocketMessage(response)
                    self.__log(websocket_message)
                    parsed_message = websocket_message.parsed_message
                    interaction_type = parsed_message.type

                    if (
                        interaction_type in (MessageTypeEnum.none, MessageTypeEnum.copilot_final, MessageTypeEnum.unknown)
                        or interaction_type == MessageTypeEnum.ping
                        and not is_user_input
                    ):
                        stop_polling = True
                        if interaction_type == MessageTypeEnum.copilot_final:
                            return websocket_message
                        elif interaction_type == MessageTypeEnum.unknown:
                            print(f"{TOOL_PROMPT} Got unknown message type : {websocket_message.message}")

    def enable_bing_web_search(self) -> None:
        if not self.__is_initialized:
            raise CopilotConnectionNotInitializedException("Copilot connection not initialized.")
        self.__conversation_params.used_plugins.append({"Id": "BingWebSearch", "Source": "BuiltIn"})

    def disable_bing_web_search(self) -> None:
        if not self.__is_initialized:
            raise CopilotConnectionNotInitializedException("Copilot connection not initialized.")
        self.__conversation_params.used_plugins = []

    def use_agent(self, agent_index: int) -> str:
        if not self.__is_initialized:
            raise CopilotConnectionNotInitializedException("Copilot connection not initialized.")
        if agent_index >= len(self.__conversation_params.available_gpts):
            print(f"Invalid agent index: {agent_index}")
            return
        agent = self.__conversation_params.available_gpts[agent_index]
        self.__conversation_params.used_agent.append(agent)
        return agent.displayName

    def use_copilot365(self) -> None:
        if not self.__is_initialized:
            raise CopilotConnectionNotInitializedException("Copilot connection not initialized.")
        self.__conversation_params.used_agent.pop()

    def __get_session_from_url(self, url: str) -> str:
        if "X-SessionId=" not in url:
            raise ValueError("Session ID not found in URL.")
        return url.split("X-SessionId=")[1].split("&")[0]

    def __get_prompt(self, prompt: str) -> dict:
        is_start_of_session = self.__index == 0
        used_agent_params = {}
        if len(self.__conversation_params.used_agent) > 0:
            used_agent = self.__conversation_params.used_agent[0]
            used_agent_params = {"id": used_agent.id, "source": used_agent.source}

        prompt_message_dict = {
            "arguments": [
                {
                    "source": self.__arguments.scenario.value,
                    "clientCorrelationId": "60c2ee92-64f1-cef5-555a-b7ad5ad2c21c",
                    "sessionId": self.__conversation_params.session_id,
                    "optionsSets": [
                        "enterprise_flux_web",
                        "enterprise_flux_work",
                        "enable_request_response_interstitials",
                        "enterprise_flux_image_v1",
                        "enterprise_toolbox_with_skdsstore",
                        "enterprise_toolbox_with_skdsstore_search_message_extensions",
                        "enable_ME_auth_interstitial",
                        "skdsstorethirdparty",
                        "enable_confirmation_interstitial",
                        "enable_plugin_auth_interstitial",
                        "enable_response_action_processing",
                        "enterprise_flux_work_gptv",
                        "enterprise_flux_work_code_interpreter",
                        "enable_batch_token_processing",
                    ],
                    "options": {},
                    "allowedMessageTypes": [
                        "Chat",
                        "Suggestion",
                        "InternalSearchQuery",
                        "InternalSearchResult",
                        "Disengaged",
                        "InternalLoaderMessage",
                        "RenderCardRequest",
                        "AdsQuery",
                        "SemanticSerp",
                        "GenerateContentQuery",
                        "SearchQuery",
                        "ConfirmationCard",
                        "AuthError",
                        "DeveloperLogs",
                    ],
                    "sliceIds": [],
                    "threadLevelGptId": used_agent_params,
                    "conversationId": self.__conversation_params.conversation_id,
                    "traceId": "6eaf112117f7ecbfa4cef5495f098e59",
                    "isStartOfSession": is_start_of_session,
                    "productThreadType": "Office",
                    "clientInfo": {"clientPlatform": "web"},
                    "message": {
                        "author": "user",
                        "inputMethod": "Keyboard",
                        "text": prompt,
                        "entityAnnotationTypes": ["People", "File", "Event", "Email", "TeamsMessage"],
                        "requestId": "6eaf112117f7ecbfa4cef5495f098e59",
                        "locationInfo": {"timeZoneOffset": 3, "timeZone": "Asia/Jerusalem"},
                        "locale": "en-US",
                        "messageType": "Chat",
                        "experienceType": "Default",
                    },
                    "plugins": self.__conversation_params.used_plugins,
                }
            ],
            "invocationId": str(self.__index),
            "target": "chat",
            "type": 4,
        }

        if used_agent_params:
            prompt_message_dict["arguments"][0]["gpts"] = [used_agent_params]

        return prompt_message_dict

    def __get_access_token(self, refresh: bool = False) -> Optional[str]:
        scenario = self.__arguments.scenario
        debugging = self.__arguments.verbose
        user = self.__arguments.user

        access_token: Optional[str] = None
        if self.__arguments.use_cached_access_token or refresh:
            if access_token := self.__get_access_token_from_cache():
                print("Access token retrieved from cache.")
                return access_token
            else:
                print(
                    "Cached substrate token not found; launching persistent Edge profile for interactive sign-in."
                )

        print("Getting access token via persistent Microsoft Edge profile (no password)...")

        module = "get_substrate_bearer_office" if scenario == CopilotScenarioEnum.officeweb else "get_substrate_bearer_teams"
        debugMode = "true" if debugging == VerboseEnum.full else "false"  # passing in boolean values as string makes it easier
        # Resolve relative to package root so auth works regardless of cwd / install mode
        puppeteer_script = (
            pathlib.Path(__file__).resolve().parents[2] / "puppeteer_get_substrate_bearer" / f"{module}.js"
        )
        try:
            # Run the Node.js script using subprocess. Env may include
            # COPILOT_CLI_BROWSER_PROFILE / COPILOT_CLI_EDGE_PATH (paths only, never secrets).
            result = subprocess.run(  # nosec
                [
                    "node",
                    str(puppeteer_script),  # nosec
                    f"user={user}",  # nosec
                    f"debugMode={debugMode}",
                ],
                capture_output=True,
                text=True,
                cwd=str(puppeteer_script.parent),
                env=os.environ.copy(),
            )

            # Print any error messages
            if result.stderr:
                print("Node.js Errors:")
                print(result.stderr)

            parsed = self.__parse_bearer_script_stdout(result.stdout)
            access_token = parsed.get("access_token")
            if not access_token or access_token == "null":
                print(
                    "Failed to get access token. Complete interactive sign-in in the Edge window "
                    "(profile: COPILOT_CLI_BROWSER_PROFILE or ~/.config/copilot-cli/msedge-profile), then retry."
                )
                return None
            self.__cache_substrate_session(
                access_token=access_token,
                oid=parsed.get("oid"),
                tid=parsed.get("tid"),
                user=parsed.get("user") or user,
            )
            print(f"Access token cached successfully in {self.__token_cache.cache_path}.")
            return access_token

        except FileNotFoundError:
            print("Node.js executable not found. Please make sure Node.js is installed and in your PATH.")
            return None

    @staticmethod
    def __parse_bearer_script_stdout(stdout: str) -> dict:
        """Parse `key:value` lines from the Node bearer helper (token is opaque; identity is separate)."""
        parsed: dict = {}
        for line in (stdout or "").splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if key in {"access_token", "oid", "tid", "user"} and value and value != "null":
                # First matching line wins for access_token (value may be long).
                parsed.setdefault(key, value)
        return parsed

    def __cache_substrate_session(
        self, access_token: str, oid: Optional[str], tid: Optional[str], user: Optional[str]
    ) -> None:
        entities = [CachedEntity(key=self._SUBSTRATE_TOKEN_CACHE_KEY, val=access_token)]
        if oid:
            entities.append(CachedEntity(key=self._SUBSTRATE_OID_CACHE_KEY, val=oid))
        if tid:
            entities.append(CachedEntity(key=self._SUBSTRATE_TID_CACHE_KEY, val=tid))
        if user:
            entities.append(CachedEntity(key=self._SUBSTRATE_USER_CACHE_KEY, val=user))
        self.__token_cache.put_tokens(entities)

    def __get_access_token_from_cache(self) -> Optional[str]:
        token = self.__token_cache.try_fetch_token(self._SUBSTRATE_TOKEN_CACHE_KEY)
        if not token:
            print("Access token does not exist in cache.")
            return None
        return token

    @staticmethod
    def __try_decode_jwt_claims(access_token: str) -> Optional[dict]:
        """
        Best-effort decode for legacy JWT-shaped tokens only.

        Access tokens must be treated as opaque per Microsoft identity platform guidance.
        Never require this path to succeed.
        """
        if not access_token or access_token.count(".") != 2:
            return None
        try:
            return jwt.decode(access_token, algorithms=["RS256"], options={"verify_signature": False})
        except Exception:
            return None

    def __resolve_substrate_identity(self, access_token: str) -> dict:
        """
        Resolve oid/tid/user without treating the access token as a data contract.

        Preference order:
        1. Identity cached alongside the token (from WS URL path / MSAL / id_token at capture time)
        2. Soft-decode only if the token happens to still be JWT-shaped (legacy caches)
        """
        oid = self.__token_cache.try_fetch_token(self._SUBSTRATE_OID_CACHE_KEY)
        tid = self.__token_cache.try_fetch_token(self._SUBSTRATE_TID_CACHE_KEY)
        user = self.__token_cache.try_fetch_token(self._SUBSTRATE_USER_CACHE_KEY)

        claims = self.__try_decode_jwt_claims(access_token)
        if claims:
            oid = oid or claims.get("oid")
            tid = tid or claims.get("tid")
            user = user or claims.get("upn") or claims.get("unique_name") or claims.get("preferred_username")

        if not oid or not tid:
            raise CopilotConnectionFailedException(
                "Could not resolve tenant/object id for the Substrate Chathub URL. "
                "Access tokens are opaque and must not be parsed; re-run without --cached-token "
                "so the CLI can capture oid/tid from the WebSocket URL or MSAL cache."
            )

        return {"oid": oid, "tid": tid, "user": user}

    def __get_websocket_url(self, bearer_token: str, scenario: CopilotScenarioEnum, identity: dict) -> str:
        session_id = uuid.uuid4()
        client_request_id = uuid.uuid4()

        tenant_id = identity.get("tid")
        object_id = identity.get("oid")

        if not tenant_id or not object_id:
            raise ValueError("Failed to resolve tenant_id or object_id for bearer token.")

        prefix = f"wss://substrate.office.com/m365Copilot/Chathub/{object_id}@{tenant_id}?X-ClientRequestId={client_request_id}&X-SessionId={session_id}&access_token={bearer_token}"

        return (
            f"{prefix}&X-variants=feature.includeExternal,feature.AssistantConnectorsContentSources,3S.BizChatWprBoostAssistant,3S.EnableMEFromSkillDiscovery,feature.EnableAuthErrorMessage,EnableRequestPlugins,feature.EnableSensitivityLabels,feature.IsEntityAnnotationsEnabled,EnableUnsupportedUrlDetector&source=%22officeweb%22&scenario=officeweb"
            if scenario == CopilotScenarioEnum.officeweb
            else f"{prefix}&X-variants=feature.includeExternal,feature.AssistantConnectorsContentSources,3S.BizChatWprBoostAssistant,3S.EnableMEFromSkillDiscovery,feature.EnableAuthErrorMessage,feature.EnableRequestPlugins,3S.SKDS_EnablePluginManagement,EnableRequestPlugins,feature.EnableSensitivityLabels,feature.IsEntityAnnotationsEnabled,EnableUnsupportedUrlDetector&source=%22teamshub%22&scenario=teamshub"
        )

    def __get_available_agents(self, access_token: str) -> list:
        if self.__arguments.scenario == CopilotScenarioEnum.teamshub:
            return []

        agents: list[AgentInfoModel] = []
        url = "https://substrate.office.com/m365Copilot/GetGptList"

        url = "https://substrate.office.com/m365Copilot//GetGptList?request=%7B%22optionsSets%22%3A%5B%22flux_gpt_data_retriever_enterprise%22%2C%22plugins_as_declarative_agents%22%5D%2C%22traceId%22%3A%228883a40d990df8b1fb0c9b3166a9b78e%22%7D&variants=feature.disabledisallowedmsgs"

        headers = {"Authorization": f"Bearer {access_token}", "X-Scenario": "officeweb"}

        agents_response = requests.get(url, headers=headers)  # nosec
        if agents_response.status_code != 200:
            if agents_response.status_code == 401:
                raise CopilotConnectionFailedException("Unauthorized. Try to delete cached token and retry")
            print(f"Failed to get agents. Error: {agents_response.text}. status_code: {agents_response.status_code}")
            return []
        for index, agent in enumerate(agents_response.json().get("gptList", [])):
            gpt_identifier = agent.get("gptIdentifier")
            agents.append(
                AgentInfoModel(
                    index=index,
                    id=gpt_identifier["id"],
                    displayName=agent["name"],
                    version=gpt_identifier.get("version", "N/A"),
                    description=agent.get("description", "N/A"),
                    source=gpt_identifier["source"],
                    type=agent.get("type"),
                )
            )
        return agents

    def __get_conversation_parameters(self, refresh: bool = False) -> ConversationParameters:
        print("Getting bearer token...")
        access_token = self.__get_access_token(refresh)
        if not access_token:
            print("Failed to get bearer token. Exiting...")
            raise CopilotConnectionFailedException("Could not get access token to connect to copilot.")

        identity = self.__resolve_substrate_identity(access_token)
        token_user = identity.get("user")
        if token_user and self.__arguments.user and self.__arguments.user.lower() != str(token_user).lower():
            raise CopilotConnectedUserMismatchException(
                "Cached token is not for the user provided in the arguments."
            )

        print("Acquired bearer token successfully.")
        url = self.__get_websocket_url(access_token, self.__arguments.scenario, identity)
        session_id = self.__get_session_from_url(url)

        available_agents: list[AgentInfoModel] = self.__get_available_agents(access_token)

        return ConversationParameters(
            conversation_id=str(uuid.uuid4()), url=url, session_id=session_id, used_plugins=[], available_gpts=available_agents, used_agent=[]
        )

    def __log(self, message: WebsocketMessage) -> None:
        if self.__arguments.verbose == VerboseEnum.off or not self.__file_logger:
            return None
        elif (
            self.__arguments.verbose == VerboseEnum.mid and message.type() != MessageTypeEnum.copilot
        ) or self.__arguments.verbose == VerboseEnum.full:
            self.__file_logger.log(message.message)

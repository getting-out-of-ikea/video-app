"""LiveKit Agents worker backing the webapp's /bot/[nome] conversations.

Run it with::

    uv run bot-agent dev      # local development, connected to LiveKit Cloud
    uv run bot-agent start    # production

The worker registers itself under the name ``llm-bot``; the webapp asks for it
through the ``roomConfig.agents`` field of the access token it mints in
``webapp/src/routes/api/token/+server.ts``. The two names must stay in sync.

The pipeline is STT -> LLM -> TTS:

* STT and TTS run locally, on top of the helpers in :mod:`bot_agent.stt_tts`
  (faster-whisper and Piper) via the adapters in :mod:`bot_agent.plugins`;
* the LLM is a remote OpenAI-compatible endpoint. DeepSeek is the default
  (``LLM_BASE_URL`` defaults to their API, ``LLM_MODEL`` to ``deepseek-chat``),
  but any compatible service works by changing those two variables.

Everything that can be configured lives in the environment; see
``bot-agent/.env.example``.
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.plugins import openai, silero

from .plugins import PiperTTS, WhisperSTT

# Must match the agent name dispatched by the webapp's token endpoint.
AGENT_NAME = "llm-bot"

DEFAULT_LANGUAGE = "it"
DEFAULT_LLM_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_LLM_MODEL = "deepseek-chat"
DEFAULT_WHISPER_MODEL = "base"
DEFAULT_SPEED = "0.7"

DEFAULT_INSTRUCTIONS = (
    "Sei un assistente vocale che conversa a voce con l'utente. "
    "Rispondi in modo conciso e cordiale, in una o due frasi, "
    "come in una telefonata."
)

GREETING = "Saluta l'utente in una frase e chiedigli come puoi aiutarlo."

logger = logging.getLogger("bot-agent")


def _optional_env(name: str) -> str | None:
    """Read an env var, treating an empty string as "not set"."""
    value = os.getenv(name)
    return value if value else None


class Bot(Agent):
    """The conversational persona. Instructions come from BOT_INSTRUCTIONS."""

    def __init__(self) -> None:
        super().__init__(
            instructions=_optional_env("BOT_INSTRUCTIONS") or DEFAULT_INSTRUCTIONS
        )


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    language = _optional_env("BOT_LANGUAGE") or DEFAULT_LANGUAGE
    logger.info("starting llm-bot session (language=%s)", language)

    # Read the API key up front so a missing .env fails with a clear message
    # here, instead of surfacing later as an opaque 401 from the LLM provider.
    # We pass it to the plugin explicitly rather than relying on OPENAI_API_KEY,
    # so the worker never silently falls back to an OpenAI account.
    llm_api_key = _optional_env("LLM_API_KEY")
    if not llm_api_key:
        raise RuntimeError(
            "LLM_API_KEY is not set. Copy bot-agent/.env.example to .env and "
            "fill in your provider's API key."
        )

    # Constructing the plugins is synchronous and loads the local models.
    # That is deliberate (and matches how livekit's own silero.VAD.load() is
    # used): the job starts a fraction of a second slower, and the first
    # utterance never pays for the model load.
    session = AgentSession(
        # Both plugins are non-streaming, so the framework needs a VAD to cut
        # the incoming audio into utterances before transcribing them.
        vad=silero.VAD.load(),
        stt=WhisperSTT(
            language=language,
            model_size=_optional_env("WHISPER_MODEL") or DEFAULT_WHISPER_MODEL,
        ),
        # The plugin name is `openai`, but the service is whatever LLM_BASE_URL
        # points at. DeepSeek by default.
        llm=openai.LLM(
            model=_optional_env("LLM_MODEL") or DEFAULT_LLM_MODEL,
            base_url=_optional_env("LLM_BASE_URL") or DEFAULT_LLM_BASE_URL,
            api_key=llm_api_key,
        ),
        tts=PiperTTS(
            language=language,
            voice=_optional_env("BOT_VOICE"),
            speed=float(_optional_env("BOT_SPEED") or DEFAULT_SPEED),
        ),
        # Publish both sides of the conversation into the room: the webapp
        # renders them from RoomEvent.TranscriptionReceived.
        transcription_enabled=True,
    )

    await session.start(room=ctx.room, agent=Bot())
    await session.generate_reply(instructions=GREETING)


def main() -> None:
    # livekit's CLI does load .env itself, but doing it here too makes the
    # behaviour independent of the version and keeps the failure mode obvious.
    load_dotenv()
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name=AGENT_NAME))

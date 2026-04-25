import asyncio
import base64
import logging
import os
from typing import Optional

from fastapi import WebSocket
from google import genai
from google.genai import types
from app.core.settings import settings

logger = logging.getLogger(__name__)

INPUT_AUDIO_RATE = settings.input_audio_rate
DEFAULT_OUTPUT_AUDIO_RATE = settings.output_audio_rate


class LiveVoiceBridge:
    def __init__(self, websocket: WebSocket, api_key: str, model: str, prompt: str, voice: str):
        self.websocket = websocket
        self.api_key = api_key
        self.model = model
        self.prompt = prompt
        self.voice = voice

    async def run(self) -> None:
        client = genai.Client(api_key=self.api_key)
        connect_config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice)
                )
            ),
            system_instruction=self.prompt,
        )

        async with client.aio.live.connect(model=self.model, config=connect_config) as session:
            sender = asyncio.create_task(self._browser_to_gemini(session))
            receiver = asyncio.create_task(self._gemini_to_browser(session))
            done, pending = await asyncio.wait(
                {sender, receiver}, return_when=asyncio.FIRST_EXCEPTION
            )

            for task in pending:
                task.cancel()

            for task in done:
                exc = task.exception()
                if exc is not None:
                    raise exc

    async def _browser_to_gemini(self, session: "genai.live.AsyncSession") -> None:
        while True:
            payload = await self.websocket.receive_json()
            msg_type = payload.get("type")

            if msg_type == "audio_in":
                b64 = payload.get("pcm16")
                if not b64:
                    continue
                pcm_bytes = base64.b64decode(b64)
                await session.send_realtime_input(
                    audio=types.Blob(
                        data=pcm_bytes, mime_type=f"audio/pcm;rate={INPUT_AUDIO_RATE}"
                    )
                )
            elif msg_type == "audio_stream_end":
                # Backward compatibility: prefer activity_end for multi-turn sessions.
                await session.send_realtime_input(audio_stream_end=True)
            elif msg_type == "activity_start":
                await session.send_realtime_input(activity_start=types.ActivityStart())
            elif msg_type == "activity_end":
                await session.send_realtime_input(activity_end=types.ActivityEnd())
            elif msg_type == "text":
                text = (payload.get("text") or "").strip()
                if text:
                    await session.send(input=text, end_of_turn=True)
            elif msg_type == "ping":
                await self.websocket.send_json({"type": "pong"})
            elif msg_type == "close":
                return

    async def _gemini_to_browser(self, session: "genai.live.AsyncSession") -> None:
        while True:
            async for message in session.receive():
                if message.setup_complete:
                    await self.websocket.send_json({"type": "ready"})

                server_content = message.server_content
                if not server_content:
                    continue

                if getattr(server_content, "interrupted", False):
                    await self.websocket.send_json({"type": "interrupted"})

                if server_content.input_transcription and server_content.input_transcription.text:
                    await self.websocket.send_json(
                        {
                            "type": "input_transcript",
                            "text": server_content.input_transcription.text,
                        }
                    )

                if server_content.output_transcription and server_content.output_transcription.text:
                    await self.websocket.send_json(
                        {
                            "type": "output_transcript",
                            "text": server_content.output_transcription.text,
                        }
                    )

                model_turn = server_content.model_turn
                if model_turn:
                    for part in model_turn.parts or []:
                        if part.text:
                            await self.websocket.send_json({"type": "text", "text": part.text})
                        if part.inline_data and part.inline_data.data:
                            mime = part.inline_data.mime_type or "audio/pcm"
                            await self.websocket.send_json(
                                {
                                    "type": "audio_out",
                                    "pcm16": base64.b64encode(part.inline_data.data).decode(
                                        "utf-8"
                                    ),
                                    "mime_type": mime,
                                    "sample_rate": self._extract_sample_rate(mime),
                                }
                            )

                if server_content.turn_complete:
                    await self.websocket.send_json(
                        {
                            "type": "turn_complete",
                            "reason": str(server_content.turn_complete_reason or ""),
                        }
                    )

    @staticmethod
    def _extract_sample_rate(mime_type: Optional[str]) -> int:
        if not mime_type:
            return DEFAULT_OUTPUT_AUDIO_RATE
        for token in mime_type.split(";"):
            token = token.strip().lower()
            if token.startswith("rate="):
                value = token.split("=", 1)[1]
                if value.isdigit():
                    return int(value)
        return DEFAULT_OUTPUT_AUDIO_RATE



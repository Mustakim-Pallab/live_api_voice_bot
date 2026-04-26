import asyncio
import base64
import logging
import os
import wave
import datetime
import json
from google.cloud import storage
from typing import Optional

from fastapi import WebSocket
from google import genai
from google.genai import types
from app.core.settings import settings
from app.services.session_manager import session_manager

logger = logging.getLogger(__name__)

INPUT_AUDIO_RATE = settings.input_audio_rate
DEFAULT_OUTPUT_AUDIO_RATE = settings.output_audio_rate


class LiveVoiceBridge:
    def __init__(self, websocket: WebSocket, api_key: str, model: str, prompt: str, voice: str, session_id: str, agent_id: str):
        self.websocket = websocket
        self.api_key = api_key
        self.model = model
        self.prompt = prompt
        self.voice = voice
        self.session_id = session_id
        self.agent_id = agent_id
        self.session_manager = session_manager
        
        # Recording state
        self.transcript = []
        self.audio_dir = "recordings"
        os.makedirs(self.audio_dir, exist_ok=True)
        self.turn_index = 0
        self.turns_audio = {0: {"user": bytearray(), "bot": bytearray()}}

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
            try:
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
                        # Log it but don't raise it immediately so we can finalize
                        logger.warning(f"Task exception in LiveVoiceBridge: {exc}")
            finally:
                # Save recording to DB and finalize audio
                await self._finalize_recording()

    async def _browser_to_gemini(self, session: "genai.live.AsyncSession") -> None:
        while True:
            payload = await self.websocket.receive_json()
            msg_type = payload.get("type")

            if msg_type == "audio_in":
                b64 = payload.get("pcm16")
                if not b64:
                    continue
                pcm_bytes = base64.b64decode(b64)
                
                # Save user audio output
                if self.turn_index in self.turns_audio:
                    self.turns_audio[self.turn_index]["user"].extend(pcm_bytes)
                else:
                    logger.warning(f"Audio in for untracked turn index {self.turn_index}")
                
                await session.send_realtime_input(
                    audio=types.Blob(
                        data=pcm_bytes, mime_type=f"audio/pcm;rate={INPUT_AUDIO_RATE}"
                    )
                )
                # Broadcast audio_in to monitors
                await self.session_manager.broadcast_to_monitors(self.session_id, payload)
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
                    # Broadcast text input to monitors
                    await self.session_manager.broadcast_to_monitors(self.session_id, payload)
                    self.transcript.append({"role": "user", "text": text, "timestamp": str(datetime.datetime.utcnow())})
            elif msg_type == "ping":
                await self.websocket.send_json({"type": "pong"})
            elif msg_type == "close":
                return

    async def _gemini_to_browser(self, session: "genai.live.AsyncSession") -> None:
        while True:
            async for message in session.receive():
                if message.setup_complete:
                    await self.websocket.send_json({"type": "ready"})
                    await self.session_manager.broadcast_to_monitors(self.session_id, {"type": "ready"})

                server_content = message.server_content
                if not server_content:
                    continue

                if getattr(server_content, "interrupted", False):
                    await self.websocket.send_json({"type": "interrupted"})
                    await self.session_manager.broadcast_to_monitors(self.session_id, {"type": "interrupted"})

                if server_content.input_transcription and server_content.input_transcription.text:
                    msg = {
                        "type": "input_transcript",
                        "text": server_content.input_transcription.text,
                    }
                    await self.websocket.send_json(msg)
                    await self.session_manager.broadcast_to_monitors(self.session_id, msg)
                    self.transcript.append({"role": "user", "text": msg["text"], "timestamp": str(datetime.datetime.utcnow())})

                if server_content.output_transcription and server_content.output_transcription.text:
                    msg = {
                        "type": "output_transcript",
                        "text": server_content.output_transcription.text,
                    }
                    await self.websocket.send_json(msg)
                    await self.session_manager.broadcast_to_monitors(self.session_id, msg)
                    self.transcript.append({"role": "bot", "text": msg["text"], "timestamp": str(datetime.datetime.utcnow())})

                model_turn = server_content.model_turn
                if model_turn:
                    for part in model_turn.parts or []:
                        if part.text:
                            msg = {"type": "text", "text": part.text}
                            await self.websocket.send_json(msg)
                            await self.session_manager.broadcast_to_monitors(self.session_id, msg)
                            self.transcript.append({"role": "bot", "text": msg["text"], "timestamp": str(datetime.datetime.utcnow())})
                        if part.inline_data and part.inline_data.data:
                            mime = part.inline_data.mime_type or "audio/pcm"
                            msg = {
                                "type": "audio_out",
                                "pcm16": base64.b64encode(part.inline_data.data).decode(
                                    "utf-8"
                                ),
                                "mime_type": mime,
                                "sample_rate": self._extract_sample_rate(mime),
                            }
                            await self.websocket.send_json(msg)
                            await self.session_manager.broadcast_to_monitors(self.session_id, msg)
                            # Save bot audio output
                            if self.turn_index in self.turns_audio:
                                self.turns_audio[self.turn_index]["bot"].extend(part.inline_data.data)
                            else:
                                logger.warning(f"Audio out for untracked turn index {self.turn_index}")

                if server_content.turn_complete:
                    self.turn_index += 1
                    self.turns_audio[self.turn_index] = {"user": bytearray(), "bot": bytearray()}
                    
                    msg = {
                        "type": "turn_complete",
                        "reason": str(server_content.turn_complete_reason or ""),
                    }
                    await self.websocket.send_json(msg)
                    await self.session_manager.broadcast_to_monitors(self.session_id, msg)

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

    async def _finalize_recording(self):
        try:
            import wave
            import os
            import audioop
            import json
            import datetime
            import uuid
            from app.db.database import SessionLocal
            from app.models.call_record import CallRecordModel

            def trim_silence(data, threshold=500):
                if not data: return data
                # 16-bit mono: 2 bytes per sample. 10ms at 16kHz = 320 bytes
                chunk_size = 320
                
                # Trim leading
                start_idx = 0
                for i in range(0, len(data), chunk_size):
                    chunk = data[i:i+chunk_size]
                    if len(chunk) < chunk_size: break
                    if audioop.rms(chunk, 2) > threshold:
                        start_idx = i
                        break
                else:
                    return bytearray() # Entirely silent
                
                data = data[start_idx:]
                
                # Trim trailing
                end_idx = len(data)
                for i in range(len(data) - chunk_size, -1, -chunk_size):
                    chunk = data[i:i+chunk_size]
                    if audioop.rms(chunk, 2) > threshold:
                        end_idx = i + chunk_size
                        break
                else:
                    return bytearray()

                return data[:end_idx]
            uploaded_urls = []
            full_audio = bytearray()
            target_rate = DEFAULT_OUTPUT_AUDIO_RATE # Usually 24000
            
            # 1. Process individual turns and build full_audio
            logger.info(f"Finalizing recording for session {self.session_id}. Turns: {list(self.turns_audio.keys())}")
            for turn_idx in sorted(self.turns_audio.keys()):
                audio_data = self.turns_audio[turn_idx]
                turn_urls = {"turn": turn_idx}
                
                user_len = len(audio_data["user"])
                bot_len = len(audio_data["bot"])
                logger.debug(f"Turn {turn_idx}: User audio {user_len} bytes, Bot audio {bot_len} bytes")

                # User Audio
                if user_len > 0:
                    # Resample user audio (16k -> 24k) to match bot
                    try:
                        # Trim both leading and trailing silence to eliminate inter-turn delays
                        raw_user = bytes(audio_data["user"])
                        trimmed_user = trim_silence(raw_user)
                        logger.info(f"Turn {turn_idx}: User audio trimmed from {len(raw_user)} to {len(trimmed_user)} bytes")
                        
                        if len(trimmed_user) > 0:
                            resampled_user, _ = audioop.ratecv(
                                trimmed_user, 2, 1, INPUT_AUDIO_RATE, target_rate, None
                            )
                            full_audio.extend(resampled_user)
                        logger.debug(f"Resampled user audio turn {turn_idx}: {len(resampled_user)} bytes")
                    except Exception as resample_err:
                        logger.error(f"Failed to resample user audio turn {turn_idx}: {resample_err}")
                        full_audio.extend(audio_data["user"]) # Fallback
                    
                    user_wav = f"{self.audio_dir}/{self.session_id}_turn_{turn_idx}_user.wav"
                    try:
                        with wave.open(user_wav, "wb") as wav_f:
                            wav_f.setnchannels(1)
                            wav_f.setsampwidth(2)
                            wav_f.setframerate(INPUT_AUDIO_RATE)
                            wav_f.writeframes(audio_data["user"])
                        url = self._upload_to_gcs(user_wav, f"recordings/{self.session_id}/turn_{turn_idx}_user.wav")
                        if url:
                            turn_urls["user_url"] = url
                    finally:
                        if os.path.exists(user_wav): os.remove(user_wav)

                # Bot Audio
                if bot_len > 0:
                    full_audio.extend(audio_data["bot"])
                    
                    bot_wav = f"{self.audio_dir}/{self.session_id}_turn_{turn_idx}_bot.wav"
                    try:
                        with wave.open(bot_wav, "wb") as wav_f:
                            wav_f.setnchannels(1)
                            wav_f.setsampwidth(2)
                            wav_f.setframerate(target_rate)
                            wav_f.writeframes(audio_data["bot"])
                        url = self._upload_to_gcs(bot_wav, f"recordings/{self.session_id}/turn_{turn_idx}_bot.wav")
                        if url:
                            turn_urls["bot_url"] = url
                    finally:
                        if os.path.exists(bot_wav): os.remove(bot_wav)
                
                if "user_url" in turn_urls or "bot_url" in turn_urls:
                    uploaded_urls.append(turn_urls)

            # 2. Save and Upload Full Merged Audio
            merged_url = None
            if len(full_audio) > 0:
                logger.info(f"Saving merged audio: {len(full_audio)} bytes")
                merged_wav = f"{self.audio_dir}/{self.session_id}_full.wav"
                try:
                    with wave.open(merged_wav, "wb") as wav_f:
                        wav_f.setnchannels(1)
                        wav_f.setsampwidth(2)
                        wav_f.setframerate(target_rate)
                        wav_f.writeframes(bytes(full_audio))
                    
                    if os.path.exists(merged_wav):
                        fsize = os.path.getsize(merged_wav)
                        logger.info(f"Merged WAV file size on disk: {fsize} bytes")
                        if fsize > 44:
                            merged_url = self._upload_to_gcs(merged_wav, f"recordings/{self.session_id}/full.wav")
                        else:
                            logger.warning("Merged WAV file is empty (header only)")
                finally:
                    if os.path.exists(merged_wav): os.remove(merged_wav)
            else:
                logger.warning(f"No audio collected for session {self.session_id}")

            # 3. Save to Database
            db = SessionLocal()
            try:
                # Save both merged and turn-by-turn audio links
                audio_data_json = json.dumps({
                    "merged": merged_url,
                    "turns": uploaded_urls
                })
                
                # Calculate actual duration of merged audio
                duration_sec = len(full_audio) / (2 * target_rate) if full_audio else 0
                duration_str = f"{int(duration_sec // 60)}:{int(duration_sec % 60):02d}"
                
                record = CallRecordModel(
                    id=str(uuid.uuid4()),
                    session_id=self.session_id,
                    agent_id=self.agent_id,
                    start_time=datetime.datetime.utcnow(),
                    end_time=datetime.datetime.utcnow(),
                    transcript=json.dumps(self.transcript),
                    audio_path=audio_data_json,
                    duration=duration_str
                )
                db.add(record)
                db.commit()
                logger.info(f"Saved complete call record for session {self.session_id} with both merged and turn audio.")
            except Exception as db_err:
                logger.error(f"Failed to save call record: {db_err}")
            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error finalizing recording: {e}", exc_info=True)


    def _upload_to_gcs(self, local_file_path: str, destination_blob_name: str) -> Optional[str]:
        try:
            import os
            # Use service account file if it exists, otherwise fallback to default
            if os.path.exists(settings.gcs_service_account_path):
                storage_client = storage.Client.from_service_account_json(settings.gcs_service_account_path)
            else:
                storage_client = storage.Client()
                
            bucket = storage_client.bucket(settings.gcs_bucket_name)
            blob = bucket.blob(destination_blob_name)

            blob.upload_from_filename(local_file_path)
            return f"https://storage.googleapis.com/{settings.gcs_bucket_name}/{destination_blob_name}"
        except Exception as e:
            logger.error(f"GCS upload failed: {e}")
            return None

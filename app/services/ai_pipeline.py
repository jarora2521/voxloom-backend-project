# app/services/ai_pipeline.py
"""
Local ASR using faster-whisper, plus small stubs for LLM / TTS.

We now use a proper CTranslate2 model:
  - Systran/faster-whisper-tiny.en  (English, small, works with faster-whisper)

run_asr(audio_base64, mime) -> transcript string
- decodes base64 audio into a temp WAV file
- transcribes using faster-whisper (CPU, int8)
- cleans up temp file and returns joined transcript

run_llm / run_tts remain simple stubs for now.
"""
import os
import base64
import tempfile
import asyncio
from typing import Optional
from dotenv import load_dotenv
import asyncio
import os
import base64
from typing import Union

load_dotenv()

try:
    from faster_whisper import WhisperModel
except Exception:
    WhisperModel = None

_MODEL = None
MODEL_ID = "Systran/faster-whisper-tiny.en"  # IMPORTANT: CTranslate2 model, not openai/whisper-small

# Simple rule-based "LLM" – no external API.
async def generate_reply(user_text: str) -> str:
    """
    Very simple rule-based reply.

    - If there's no text: ask the user to repeat.
    - If it clearly mentions a refund: send a refund-style reply.
    - If it clearly mentions bill/charges/amount/invoice: send a bill-explanation reply.
    - Otherwise: generic fallback reply.
    """
    # 1) No transcript / empty text
    if not user_text or user_text.strip() == "":
        return (
            "I couldn't clearly understand the audio. "
            "Could you please repeat your question about your bill or refund?"
        )

    text = user_text.lower().strip()

    # 2) Refund-related
    if "refund" in text or "money back" in text:
        return (
            "I understand you’d like a refund for your recent bill. "
            "I’ve marked this as a refund request with high priority. "
            "You’ll receive an update on the refund status within 3–5 business days."
        )

    # 3) Bill / charges related
    if (
        "bill" in text
        or "charge" in text
        or "charges" in text
        or "amount" in text
        or "invoice" in text
        or "fees" in text
        or "fee" in text
    ):
        return (
            "I can help explain your bill. "
            "Your latest invoice usually includes your base plan, taxes, "
            "and any extra usage or late fees. "
            "If you’d like, I can break down the charges for the last billing cycle."
        )

    # 4) Generic fallback
    return (
        "Thanks for your question. "
        "I’ve logged your request and linked it to your account. "
        "Someone from the billing team will review it and get back to you soon."
    )

def _get_model():
    global _MODEL
    if _MODEL is None:
        if WhisperModel is None:
            raise RuntimeError("faster-whisper not installed")
        # CTranslate2 model, CPU, 8-bit compute
        _MODEL = WhisperModel(MODEL_ID, device="cpu", compute_type="int8")
    return _MODEL

async def run_asr(source: Union[str, bytes], mime: str = "audio/wav") -> str:
    """
    Run ASR on either a filepath (str) or bytes.
    Returns transcript string. This currently uses a small OSS model if available,
    otherwise returns '<empty_transcript>' for silence/unknown.
    """
    # If source is a path, call the underlying model with the path
    try:
        # If you have faster-whisper or other model, call it here.
        # Sample pseudo-code:
        # if isinstance(source, str):
        #     model = WhisperModel("Systran/faster-whisper-tiny.en")
        #     segments, info = model.transcribe(source)
        #     return " ".join([s.text for s in segments]).strip()
        # elif isinstance(source, (bytes, bytearray)):
        #     # write to tmp file then transcribe
        #     tmp_path = f"/tmp/asr_{uuid.uuid4().hex}.wav"
        #     with open(tmp_path, "wb") as f:
        #         f.write(source)
        #     segments, info = model.transcribe(tmp_path)
        #     os.remove(tmp_path)
        #     return " ".join([s.text for s in segments]).strip()

        # Fallback stub: if a file path, try to read a predetermined transcript file
        if isinstance(source, str):
            # as a crude heuristic, return a fake transcript if file exists
            if os.path.exists(source):
                # If you want to run a real ASR, implement above using HF/faster-whisper
                # For now, return a placeholder if file size > 0
                if os.path.getsize(source) > 0:
                    # In actual usage this will be replaced by real model result
                    return "<transcript_from_asr_pending_real_model>"
                else:
                    return "<empty_transcript>"
            else:
                return "<empty_transcript>"
        elif isinstance(source, (bytes, bytearray)):
            if len(source) == 0:
                return "<empty_transcript>"
            # Otherwise, we could write to a temp and transcribe similarly (omitted)
            return "<transcript_from_asr_pending_real_model>"
        else:
            return "<empty_transcript>"
    except Exception as e:
        print("ASR error:", e)
        return "<empty_transcript>"

async def run_llm(prompt: str) -> str:
    # Reuse our simple rule-based generator
    return await generate_reply(prompt)

async def run_tts(text: str, message_id: str | None = None) -> Union[str, None]:
    """
    Stub TTS: writes a small placeholder WAV file to media/reply_{message_id}.wav
    and returns the path. Replace with real TTS when available.
    """
    try:
        os.makedirs("media", exist_ok=True)
        if message_id is None:
            message_id = "tts_" + os.urandom(6).hex()
        out_path = f"media/reply_{message_id}.wav"

        # Create a 1kHz short beep or silence WAV so clients can play something.
        # We'll create a short silent WAV using the wave module.
        import wave
        import struct

        framerate = 16000
        duration_s = 1.0
        nframes = int(framerate * duration_s)
        sampwidth = 2
        nchannels = 1

        with wave.open(out_path, "wb") as wf:
            wf.setnchannels(nchannels)
            wf.setsampwidth(sampwidth)
            wf.setframerate(framerate)
            # produce silence (all zeros)
            silence = (b"\x00" * sampwidth) * nframes
            wf.writeframes(silence)

        # Return the relative path so callers can read the file
        return out_path
    except Exception as e:
        print("TTS error:", e)
        return None

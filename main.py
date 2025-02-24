import os
import io
import base64
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi import Body
from pymongo import MongoClient
from cartesia import Cartesia
from groq import Groq
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize FastAPI
app = FastAPI()

# MongoDB Connection
mongo_client = MongoClient(os.getenv("MONGODB_URI"))
db = mongo_client["spam_blocker"]
collection = db["calls"]

# Groq API Setup
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_API_KEY)

# Cartesia TTS Setup
CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY")
cartesia_client = Cartesia(api_key=CARTESIA_API_KEY)

# Default Personality Prompt
DEFAULT_PROMPT = (
    "You are an AI-powered call-handling assistant trained to respond to unknown callers. "
    "Your goal is to keep the conversation going for as long as possible while sounding like a real human. "
    "Ask follow-up questions, act slightly curious, and try to prolong the chat without revealing personal information."
    "Don't ask too many questions in single turn. Response should be concise and engaging."
)

# 1. Real-Time Speech-to-Text (STT) using Groq Whisper v3
def transcribe_audio(audio_file: bytes):
    response = groq_client.audio.transcriptions.create(
        file=("audio.m4a", audio_file),
        model="whisper-large-v3",
        response_format="verbose_json"
    )
    return response.text

# 2. Retrieve Chat History from MongoDB
def get_chat_history(caller_number: str, conversation_field: str = "conversation"):
    existing_chat = collection.find_one({"caller_number": caller_number})
    return existing_chat[conversation_field] if existing_chat and conversation_field in existing_chat else []

# 3. Generate AI Response using Groq LLaMA 3.3 70B (Default Prompt Only)
def generate_ai_response(user_input: str, caller_number: str, conversation_field: str = "conversation", user_key: str = "caller"):
    chat_history = get_chat_history(caller_number, conversation_field)
    messages = [{"role": "system", "content": DEFAULT_PROMPT}]

    # Append conversation history
    for entry in chat_history:
        messages.append({"role": "user", "content": entry.get(user_key, "")})
        messages.append({"role": "assistant", "content": entry.get("bot", "")})

    # Add latest user message
    messages.append({"role": "user", "content": user_input})

    completion = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=1,
        max_completion_tokens=64,
        top_p=1,
        stream=False,
        stop=None,
    )
    return completion.choices[0].message.content

# 4. Convert AI Response to Speech using Cartesia TTS
def text_to_speech(text: str):
    audio_bytes = cartesia_client.tts.bytes(
        model_id="sonic",
        transcript=text,
        voice_id="694f9389-aac1-45b6-b726-9d9369183238",  # Barbershop Man voice
        output_format={
            "container": "wav",
            "encoding": "pcm_f32le",
            "sample_rate": 44100,
        },
    )
    return audio_bytes

# API Endpoint for Handling Calls
@app.post("/handle-call/")
async def handle_call(caller_number: str, audio: UploadFile = File(...)):
    # Read the uploaded audio file
    audio_bytes = await audio.read()
    # Convert audio to text (STT)
    transcribed_text = transcribe_audio(audio_bytes)
    # Generate AI response using the default prompt
    bot_response = generate_ai_response(transcribed_text, caller_number)
    # Convert AI response to speech (TTS) synchronously
    tts_audio = text_to_speech(bot_response)
    # Store the conversation in MongoDB (for voice calls)
    collection.update_one(
        {"caller_number": caller_number},
        {"$push": {"conversation": {"caller": transcribed_text, "bot": bot_response}}},
        upsert=True
    )
    # Base64 encode the binary audio so it can be included in JSON
    import base64
    tts_audio_base64 = base64.b64encode(tts_audio).decode("utf-8")

    response_data = {
        "caller_number": caller_number,
        "transcribed_text": transcribed_text,
        "bot_response": bot_response,
        "tts_audio": tts_audio_base64,  # JSON-compatible audio
    }
    return response_data


@app.post("/handle-sms/")
async def handle_sms(
    caller_number: str = Body(...),
    message: str = Body(...)
):
    # Save the incoming SMS message in the "sms_conversation" field
    collection.update_one(
        {"caller_number": caller_number},
        {"$push": {"sms_conversation": {"user": message}}},
        upsert=True
    )
    # Generate a bot response for the SMS using the default prompt
    bot_response = generate_ai_response(
        message, caller_number,
        conversation_field="sms_conversation", user_key="user"
    )
    # Update the SMS conversation with the bot's reply
    collection.update_one(
        {"caller_number": caller_number},
        {"$push": {"sms_conversation": {"bot": bot_response}}},
        upsert=True
    )
    return {
        "caller_number": caller_number,
        "user_message": message,
        "bot_response": bot_response
    }

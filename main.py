import os
import io
import base64
import asyncio
import urllib.parse
from fastapi import FastAPI, UploadFile, File, Body, Form, HTTPException
from fastapi.responses import JSONResponse, Response
from pymongo import MongoClient
from cartesia import Cartesia
from groq import Groq
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

# ---------------------------
# API Client Setup for Groq and Cartesia
# ---------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_API_KEY)

CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY")
cartesia_client = Cartesia(api_key=CARTESIA_API_KEY)

# ---------------------------
# OpenAI Chat Client Setup (using langchain_openai)
# ---------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="gpt-4o",
    temperature=1,
    max_tokens=1024,
    api_key=OPENAI_API_KEY
)

# ---------------------------
# FastAPI and MongoDB Setup
# ---------------------------
app = FastAPI()

MONGO_USER = os.getenv("MONGO_USER")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
MONGO_CLUSTER = os.getenv("MONGO_CLUSTER")

if not (MONGO_USER and MONGO_PASSWORD and MONGO_CLUSTER):
    raise Exception("Missing MongoDB environment variables.")

MONGO_DETAILS = f"mongodb+srv://{urllib.parse.quote_plus(MONGO_USER)}:{urllib.parse.quote_plus(MONGO_PASSWORD)}@{MONGO_CLUSTER}/"
mongo_client = MongoClient(MONGO_DETAILS)
database = mongo_client["contacts_db"]
contacts_collection = database["contacts"]
chat_history_collection = database["chat_history"]

# ---------------------------
# Classification Helper using LLM (for text messages only)
# ---------------------------
def classify_message_content(message: str) -> str:
    prompt = (
        "Classify the following message as either 'spam' or 'unknown'. "
        "Respond with only one word: spam or unknown.\n"
        f"Message: \"{message}\""
    )
    response = llm.invoke([{"role": "system", "content": prompt}])
    if hasattr(response, "content"):
        result = response.content.lower().strip()
    else:
        result = str(response).lower().strip()
    return "spam" if "spam" in result else "unknown"

# ---------------------------
# Pydantic Models
# ---------------------------
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional

class Contact(BaseModel):
    phone: str = Field(..., example="+1234567890")
    name: Optional[str] = Field(None, example="John Doe")
    email: Optional[EmailStr] = Field(None, example="john.doe@example.com")

class IncomingMessage(BaseModel):
    phone: str = Field(..., example="+1234567890")
    message: str = Field(..., example="Hello, can we chat?")

# ---------------------------
# Chat History Helper Functions
# ---------------------------
def get_chat_history(caller_number: str) -> List[dict]:
    doc = chat_history_collection.find_one({"caller_number": caller_number})
    if doc and "messages" in doc:
        return doc["messages"]
    return []

def update_chat_history(caller_number: str, role: str, content: str):
    chat_history_collection.update_one(
        {"caller_number": caller_number},
        {"$push": {"messages": {"role": role, "content": content}}},
        upsert=True
    )

# ---------------------------
# Conversation Simulation Functions
# ---------------------------
def simulate_text_conversation(caller_number: str, initial_message: str, conversation_type: str = "unknown") -> str:
    if conversation_type == "unknown":
        system_prompt = (
            f"You are a call assistant. The unknown caller's text message is '{initial_message}'.\n"
            "Simulate a multi-turn conversation. Do not mention that you are a virtual assistant. Act like a human"
        )
    else:
        system_prompt = "You are a call assistant. Do not mention that you are a virtual assistant. Act like a human"

    chat_history = get_chat_history(caller_number)
    messages = [{"role": "system", "content": system_prompt}]
    for entry in chat_history:
        if entry.get("role") in {"system", "user", "assistant"}:
            messages.append({"role": entry["role"], "content": entry["content"]})
    # The initial user message is already saved in chat history
    assistant_response = llm.invoke(messages)
    if hasattr(assistant_response, "content"):
        assistant_response = assistant_response.content
    else:
        assistant_response = str(assistant_response)
    
    update_chat_history(caller_number, "assistant", assistant_response)
    
    return assistant_response

def simulate_call_conversation(caller_number: str, initial_message: str, conversation_type: str = "spam") -> str:
    if conversation_type == "spam":
        system_prompt = (
            f"You are HumorBot on a phone call. The caller's number is {caller_number} and the transcribed message is '{initial_message}'.\n"
            "Simulate a multi-turn spam call conversation. Do not mention that you are a virtual assistant. Act like a human"
        )
    elif conversation_type == "unknown":
        system_prompt = (
            f"You are a call assistant. The caller's number is {caller_number} and the transcribed message is '{initial_message}'.\n"
            "Simulate a multi-turn unknown call conversation. Do not mention that you are a virtual assistant. Act like a human"
        )
    else:
        system_prompt = "You are a call assistant. Do not mention that you are a virtual assistant. Act like a human"
    
    chat_history = get_chat_history(caller_number)
    messages = [{"role": "system", "content": system_prompt}]
    for entry in chat_history:
        if entry.get("role") in {"system", "user", "assistant"}:
            messages.append({"role": entry["role"], "content": entry["content"]})
    # The transcribed message is already in chat history
    assistant_response = llm.invoke(messages)
    if hasattr(assistant_response, "content"):
        assistant_response = assistant_response.content
    else:
        assistant_response = str(assistant_response)
    
    update_chat_history(caller_number, "assistant", assistant_response)
    
    return assistant_response

# ---------------------------
# Endpoints for Contacts, Texts, and Call Forwarding Setup
# ---------------------------
@app.post("/contacts", response_model=List[Contact])
def create_contacts(contacts: List[Contact]):
    contacts_to_insert = []
    for contact in contacts:
        if contacts_collection.find_one({"phone": contact.phone}):
            raise HTTPException(status_code=400, detail=f"Contact with phone {contact.phone} already exists.")
        contacts_to_insert.append(contact.dict())
    result = contacts_collection.insert_many(contacts_to_insert)
    if not result.inserted_ids:
        raise HTTPException(status_code=500, detail="Error inserting contacts")
    return contacts

@app.get("/contacts", response_model=List[Contact])
def get_all_contacts():
    contacts = list(contacts_collection.find({}, {"_id": 0}))
    return contacts

@app.get("/contacts/{phone}", response_model=Contact)
def get_contact(phone: str):
    contact = contacts_collection.find_one({"phone": phone}, {"_id": 0})
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact

@app.post("/incoming-message")
def process_incoming_message(incoming: IncomingMessage):
    # Save the incoming message in MongoDB chat history
    update_chat_history(incoming.phone, "user", incoming.message)
    
    if contacts_collection.find_one({"phone": incoming.phone}):
        return {
            "status": "primary",
            "detail": f"Primary: {incoming.phone} – '{incoming.message}'"
        }
    
    message_classification = classify_message_content(incoming.message)
    if message_classification == "spam":
        return {
            "status": "spam",
            "detail": f"Spam: {incoming.phone} – '{incoming.message}'"
        }
    else:
        conversation_result = simulate_text_conversation(incoming.phone, incoming.message, conversation_type="unknown")
        return {
            "status": "unknown",
            "conversation_result": conversation_result
        }

@app.get("/messages/{caller_number}")
def get_messages(caller_number: str):
    messages = get_chat_history(caller_number)
    if not messages:
        raise HTTPException(status_code=404, detail="No messages found for this caller")
    return {"caller_number": caller_number, "messages": messages}

@app.post("/setup-call-forwarding")
def setup_call_forwarding():
    forwarding_number = "+1-555-123-4567"
    return {"status": "success", "message": f"Setup done! Calls forwarded to {forwarding_number}"}

# ---------------------------
# STT and TTS Functions for Voice Calls
# ---------------------------
def transcribe_audio(audio_file: bytes) -> str:
    response = groq_client.audio.transcriptions.create(
        file=("audio.m4a", audio_file),
        model="whisper-large-v3",
        response_format="verbose_json"
    )
    return response.text

def text_to_speech(text: str) -> bytes:
    audio_bytes = cartesia_client.tts.bytes(
        model_id="sonic",
        transcript=text,
        voice_id="694f9389-aac1-45b6-b726-9d9369183238",  # Example voice
        output_format={
            "container": "wav",
            "encoding": "pcm_f32le",
            "sample_rate": 44100,
        },
    )
    return audio_bytes

@app.post("/process-call")
async def process_call(caller_number: str = Form(...), audio: UploadFile = File(...)):
    if contacts_collection.find_one({"phone": caller_number}):
        ringing_text = f"Call from {caller_number} – Ringing"
        _ = text_to_speech(ringing_text)
        return {"status": "success", "message": ringing_text}
    
    try:
        audio_bytes = await audio.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading audio file: {str(e)}")
    
    try:
        transcription = transcribe_audio(audio_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during transcription: {str(e)}")
    
    update_chat_history(caller_number, "stt", transcription)
    
    conversation_result = simulate_call_conversation(caller_number, transcription, conversation_type="spam")
    
    try:
        _ = text_to_speech(conversation_result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during TTS conversion: {str(e)}")
    
    return {"status": "success", "message": "Call processed successfully."}

@app.get("/audio-reply/{caller_number}")
def get_audio_reply(caller_number: str):
    messages = get_chat_history(caller_number)
    if not messages:
        raise HTTPException(status_code=404, detail="No conversation found for this caller")
    
    stt_messages = [msg for msg in messages if msg.get("role") == "stt"]
    llm_messages = [msg for msg in messages if msg.get("role") == "assistant"]
    
    stt_response = stt_messages[-1]["content"] if stt_messages else "No STT response found."
    if not llm_messages:
        raise HTTPException(status_code=404, detail="No LLM reply available")
    llm_reply = llm_messages[-1]["content"]
    
    audio_bytes = text_to_speech(llm_reply)
    audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
    
    return {
        "caller_number": caller_number,
        "stt_response": stt_response,
        "llm_reply": llm_reply,
        "audio_reply": audio_base64
    }

# ---------------------------
# New Endpoints for Direct STT, TTS, and LLM Calls
# ---------------------------
@app.post("/stt")
async def stt_endpoint(audio: UploadFile = File(...)):
    try:
        audio_bytes = await audio.read()
        transcription = transcribe_audio(audio_bytes)
        return {"transcription": transcription}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"STT Error: {str(e)}")

@app.post("/tts")
def tts_endpoint(text: str = Body(..., embed=True)):
    try:
        audio_bytes = text_to_speech(text)
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        return {"audio": audio_base64}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS Error: {str(e)}")

@app.post("/llm")
def llm_endpoint(message: str = Body(..., embed=True)):
    try:
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": message}
        ]
        response = llm.invoke(messages)
        if hasattr(response, "content"):
            reply = response.content
        else:
            reply = str(response)
        return {"reply": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM Error: {str(e)}")

@app.get("/")
async def root():
    return {"message": "Welcome to the AI Spam Blocker API."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

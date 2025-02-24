import streamlit as st
import requests
import pymongo
import base64

# MongoDB Connection
MONGO_URI = "mongodb://localhost:27017/"  # Replace with your MongoDB URI
mongo_client = pymongo.MongoClient(MONGO_URI)
db = mongo_client["spam_blocker"]
collection = db["calls"]

# API Base URL
API_URL = "http://127.0.0.1:8000"  # Change if running backend on a different host

# Streamlit UI
st.title("📞 AI Spam Blocker Prototype")

# Sidebar Navigation
option = st.sidebar.radio("Navigation", ["📞 Simulate Call", "💬 Simulate SMS", "📜 Conversation Logs"])

# Simulate a Spam Call
if option == "📞 Simulate Call":
    st.header("📞 Simulate Spam Call")
    
    caller_number = st.text_input("Caller Number", value="+15559876543")
    uploaded_audio = st.file_uploader("Upload an Audio File (e.g., spammer voice)", type=["wav", "mp3", "m4a"])
    
    if st.button("🚀 Process Call"):
        if uploaded_audio:
            with st.spinner("Processing call..."):
                response = requests.post(
                    f"{API_URL}/handle-call/",
                    params={"caller_number": caller_number},
                    files={"audio": uploaded_audio.getvalue()}
                )
            if response.status_code != 200:
                st.error(f"API Error: {response.status_code} - {response.text}")
            else:
                result = response.json()
                if "caller_number" in result:
                    st.success("✅ Call Processed!")
                    st.write(f"**Caller:** {result['caller_number']}")
                    st.write(f"📝 **STT Transcription:** {result['transcribed_text']}")
                    st.write(f"🤖 **AI Response:** {result['bot_response']}")
                    
                    # Decode the base64 encoded audio and play it
                    audio_bytes = base64.b64decode(result["tts_audio"])
                    st.audio(audio_bytes, format="audio/wav")
                else:
                    st.error("Unexpected response format. Full response: " + str(result))
        else:
            st.error("⚠️ Please upload an audio file.")

# Simulate an SMS
elif option == "💬 Simulate SMS":
    st.header("💬 Simulate SMS Message")
    
    caller_number = st.text_input("Caller Number", value="+15559876543")
    sms_message = st.text_area("Enter Spam Message", "Congratulations! You won a free trip!")
    
    if st.button("🚀 Process SMS"):
        payload = {"caller_number": caller_number, "message": sms_message}
        with st.spinner("Processing SMS..."):
            response = requests.post(f"{API_URL}/handle-sms/", json=payload)
        if response.status_code != 200:
            st.error(f"API Error: {response.status_code} - {response.text}")
        else:
            result = response.json()
            st.success("✅ SMS Processed!")
            st.write(f"**Caller:** {result.get('caller_number', 'N/A')}")
            st.write(f"📩 **User Message:** {result.get('user_message', 'N/A')}")
            st.write(f"🤖 **AI Response:** {result.get('bot_response', 'N/A')}")

# View Conversation Logs
elif option == "📜 Conversation Logs":
    st.header("📜 Conversation Logs")
    
    caller_number = st.text_input("Enter Caller Number", value="+15559876543")
    
    if st.button("🔍 Fetch Logs"):
        with st.spinner("Fetching conversation logs..."):
            chat_history = collection.find_one({"caller_number": caller_number})
        if chat_history and "conversation" in chat_history:
            for entry in chat_history["conversation"]:
                st.write(f"👤 **User:** {entry['caller']}")
                st.write(f"🤖 **Bot:** {entry['bot']}")
                st.markdown("---")
        else:
            st.warning("No conversation history found.")

# Footer
st.markdown("---")
st.caption("🚀 AI Spam Blocker Prototype - Powered by Streamlit")

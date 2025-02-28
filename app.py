import streamlit as st
import requests
import io
import base64

BASE_URL = "http://127.0.0.1:8000"

st.title("AI Spam Blocker API Tester")

st.markdown("## Save Contact")
with st.form("save_contact_form"):
    contact_phone = st.text_input("Enter Contact Phone (e.g., +1-555-901-2345)")
    contact_name = st.text_input("Enter Contact Name (optional)", value="John Doe")
    contact_email = st.text_input("Enter Contact Email (optional)", value="john.doe@example.com")
    save_submitted = st.form_submit_button("Save Contact")
    
if save_submitted:
    if not contact_phone:
        st.error("Please enter a contact phone number.")
    else:
        payload = [{
            "phone": contact_phone,
            "name": contact_name if contact_name else None,
            "email": contact_email if contact_email else None
        }]
        with st.spinner("Saving contact..."):
            try:
                response = requests.post(f"{BASE_URL}/contacts", json=payload)
                if response.ok:
                    st.success("Contact saved successfully!")
                else:
                    st.error(f"Error: {response.status_code} {response.text}")
            except Exception as e:
                st.error(f"Exception: {str(e)}")

st.markdown("---")
st.markdown("## Call Test")

call_number = st.text_input("Enter Caller Number (e.g., +1-555-654-3210 for spam or +1-555-901-2345 for contact):", key="call_number")

st.markdown("For spam calls, upload the fake audio message below.")
audio_file = st.file_uploader("Upload Fake Audio File", type=["m4a", "wav", "mp3"], key="spam_audio")

if st.button("Test Call"):
    if not call_number:
        st.error("Please enter a caller number.")
    else:
        # First, check if the contact is saved by calling GET /contacts/{phone}
        with st.spinner("Checking contact..."):
            contact_resp = requests.get(f"{BASE_URL}/contacts/{call_number}")
        if contact_resp.ok:
            # Contact exists – show ringing message immediately.
            st.info(f"Call from {call_number} – Ringing")
        else:
            # No saved contact → treat as spam call.
            st.markdown(f"**Spam call from {call_number} – Bot replying**")
            
            # Ensure an audio file is uploaded.
            if audio_file is None:
                st.error("Please upload a fake audio file for the spam test.")
                st.stop()
            file_bytes = audio_file.read()
            
            # ----- Step 1: Call the STT endpoint -----
            with st.spinner("Processing STT..."):
                files = {"audio": (audio_file.name, io.BytesIO(file_bytes), audio_file.type)}
                stt_resp = requests.post(f"{BASE_URL}/stt", files=files)
                if stt_resp.ok:
                    stt_data = stt_resp.json()
                    transcription = stt_data.get("transcription", "No transcription")
                else:
                    st.error(f"STT Error: {stt_resp.status_code} {stt_resp.text}")
                    st.stop()
            st.markdown(f"**STT:** Transcribed ‘{transcription}’")
            
            # ----- Step 2: Call the LLM endpoint using the STT transcription -----
            with st.spinner("Processing LLM..."):
                llm_payload = {"message": transcription}
                llm_resp = requests.post(f"{BASE_URL}/llm", json=llm_payload)
                if llm_resp.ok:
                    llm_data = llm_resp.json()
                    llm_reply = llm_data.get("reply", "No reply")
                else:
                    st.error(f"LLM Error: {llm_resp.status_code} {llm_resp.text}")
                    st.stop()
            st.markdown(f"**LLM:** Bot says ‘{llm_reply}’")
            
            # ----- Step 3: Call the TTS endpoint with the LLM reply -----
            with st.spinner("Processing TTS..."):
                tts_payload = {"text": llm_reply}
                tts_resp = requests.post(f"{BASE_URL}/tts", json=tts_payload)
                if tts_resp.ok:
                    tts_data = tts_resp.json()
                    tts_audio_b64 = tts_data.get("audio", "")
                else:
                    st.error(f"TTS Error: {tts_resp.status_code} {tts_resp.text}")
                    st.stop()
            st.markdown("**TTS:** Bot audio generated from LLM response")
            
            if tts_audio_b64:
                audio_bytes = base64.b64decode(tts_audio_b64)
                st.audio(audio_bytes, format="audio/wav")
            else:
                st.info("No TTS audio returned.")

st.markdown("---")
st.markdown("## Text Test")
text_test_type = st.radio("Select Text Test Type", ("Contact Test", "Spam Test", "Unknown Test"))
text_number = st.text_input("Enter Sender Number for Text Test (e.g., +1-555-901-2345 for contact):", key="text_number")
default_text = "Hi" if text_test_type == "Contact Test" else "Free trip!" if text_test_type == "Spam Test" else "Fix your car!"
text_message = st.text_input("Enter Text Message", value=default_text, key="text_message")

if st.button("Test Text"):
    if not text_number or not text_message:
        st.error("Please enter both a number and a message.")
    else:
        payload = {"phone": text_number, "message": text_message}
        with st.spinner("Processing text message..."):
            try:
                response = requests.post(f"{BASE_URL}/incoming-message", json=payload)
                if response.ok:
                    data = response.json()
                    if "detail" in data:
                        st.success(f"Response: {data['detail']}")
                    else:
                        st.success("Conversation Result:\n" + data.get("conversation_result", ""))
                else:
                    st.error(f"Error: {response.status_code} {response.text}")
            except Exception as e:
                st.error(f"Exception: {str(e)}")

st.markdown("---")
st.markdown("## Setup Test")
if st.button("Start Setup"):
    with st.spinner("Setting up call forwarding..."):
        try:
            response = requests.post(f"{BASE_URL}/setup-call-forwarding")
            if response.ok:
                st.success(f"Response: {response.json()['message']}")
            else:
                st.error(f"Error: {response.status_code} {response.text}")
        except Exception as e:
            st.error(f"Exception: {str(e)}")

st.markdown("---")
st.markdown("## Messages History")
msg_number = st.text_input("Enter Caller Number to Retrieve Conversation History", key="msg_number")
if st.button("Get Messages"):
    if not msg_number:
        st.error("Please enter a caller number.")
    else:
        with st.spinner("Retrieving messages..."):
            try:
                response = requests.get(f"{BASE_URL}/messages/{msg_number}")
                if response.ok:
                    data = response.json()
                    st.write(data)
                else:
                    st.error(f"Error: {response.status_code} {response.text}")
            except Exception as e:
                st.error(f"Exception: {str(e)}")

import streamlit as st
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from google import genai
from google.genai import types
import tempfile
import os
import re
import yt_dlp
import requests

# --- 1. CONFIGURATION (CLOUD SAFE) ---
# We now pull these from Streamlit's hidden "Secrets" vault
SPOTIFY_CLIENT_ID = st.secrets["SPOTIFY_CLIENT_ID"]
SPOTIFY_CLIENT_SECRET = st.secrets["SPOTIFY_CLIENT_SECRET"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET))
client = genai.Client(api_key=GEMINI_API_KEY)

# --- 2. THE FSTRX PROMPT ---
# Combine Phase 1 (Deconstruction) and Phase 2 (Your 4-Filters) here
SYSTEM_PROMPT = """
PHASE 1: DECONSTRUCTIVE LISTENING
Before applying any filters, you MUST perform this internal audit:
1. TIMBRAL AUDIT: Identify specific synthesis (e.g., analog saws, FM bells). 
2. CULTURAL MOTIFS: Explicitly check for regional instruments (Koto, Erhu, Taiko). 
3. HYBRID MAPPING: Identify era fusions (e.g., 80s Retro + Modern Cinematic).

PHASE 2: THE FSTRX MECHANICS MATRIX
[INSERT YOUR ORIGINAL 4-FILTER LOGIC HERE]

***SYSTEM PARSING BLOCK***
After the "TOP 10 SELECTIONS" section, add a section called "### FSTRX_DATA_EXTRACT ###".
List ONLY the 10 final tracks in this exact format, one per line:
Track Name | Artist Name
"""

# --- 3. CORE LOGIC ---
def extract_audio(search_query_or_url):
    temp_dir = tempfile.gettempdir()
    out_tmpl = os.path.join(temp_dir, 'fstrx_audio_%(id)s.%(ext)s')
    ydl_opts = {
        'format': 'm4a/bestaudio/best',
        'outtmpl': out_tmpl,
        'quiet': True,
        'noplaylist': True,
        'nocheckcertificate': True,
        'extractor_args': {'youtube': ['player_client=default,-android_sdkless']}
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(search_query_or_url, download=True)
        if 'entries' in info: 
            info = info['entries'][0]
        return ydl.prepare_filename(info)

def process_input(text_input, audio_file):
    contents = []
    tmp_path = None
    detected_name = ""
    detected_artist = ""
    debug_log = {"pipeline_used": "Unknown", "audio_attached": False, "error_message": "None", "prompt_sent": ""}
    
    if audio_file is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            tmp.write(audio_file.getvalue())
            tmp_path = tmp.name
        debug_log["pipeline_used"] = "Tier 0: Direct MP3 Upload"
    elif "spotify.com" in text_input or "spotify:" in text_input:
        match = re.search(r"track/([a-zA-Z0-9]+)", text_input)
        if match:
            track_id = match.group(1)
            try:
                track_info = sp.track(track_id)
                detected_name, detected_artist = track_info['name'], track_info['artists'][0]['name']
                preview_url = track_info.get('preview_url')
                if preview_url:
                    response = requests.get(preview_url)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                        tmp.write(response.content)
                        tmp_path = tmp.name
                    debug_log["pipeline_used"] = "Tier 1: Spotify 30s Preview"
                else:
                    try:
                        tmp_path = extract_audio(f"ytsearch1:{detected_artist} {detected_name} official audio")
                        debug_log["pipeline_used"] = "Tier 2: YouTube Audio Rip"
                    except Exception:
                        tmp_path = extract_audio(f"scsearch1:{detected_artist} {detected_name}")
                        debug_log["pipeline_used"] = "Tier 2: SoundCloud Audio Rip"
            except Exception as e: debug_log["error_message"] = str(e)

    if tmp_path and os.path.exists(tmp_path):
        uploaded_audio = client.files.upload(file=tmp_path)
        contents.append(uploaded_audio)
        debug_log["audio_attached"] = True
        instruction = "Analyze this exact audio file using the FSTRX protocol based purely on its acoustic mechanics."
        instruction += "\n\nCRITICAL: Include the ### FSTRX_DATA_EXTRACT ### list at the end."
        contents.append(instruction)
        debug_log["prompt_sent"] = instruction
        return contents, tmp_path, debug_log
    else:
        fallback = f"Audio failed. Google Search '{detected_name}' by '{detected_artist}' for FSTRX audit."
        contents.append(fallback)
        debug_log["pipeline_used"] = "Tier 3: Text Fallback"
        return contents, None, debug_log

def get_fstrx_audit(formatted_contents):
    response = client.models.generate_content(
        model='gemini-2.5-pro',
        contents=formatted_contents,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, tools=[{"google_search": {}}])
    )
    return response.text

def parse_and_search_spotify(llm_text):
    spotify_tracks = []
    if "### FSTRX_DATA_EXTRACT ###" in llm_text:
        extraction_block = llm_text.split("### FSTRX_DATA_EXTRACT ###")[1].strip()
        for line in extraction_block.split('\n'):
            if "|" in line:
                raw_track, raw_artist = line.split("|")
                query = f"track:{raw_track.strip()} artist:{raw_artist.strip()}"
                try:
                    result = sp.search(q=query, type='track', limit=1)
                    if result['tracks']['items']:
                        t = result['tracks']['items'][0]
                        spotify_tracks.append({"name": t['name'], "artist": t['artists'][0]['name'], "url": t['external_urls']['spotify']})
                except Exception: pass
    return spotify_tracks

# --- 4. FRONTEND UI ---
st.set_page_config(page_title="FSTRX Engine", layout="wide")
st.title("FSTRX Production Supervisor Engine")
if 'audit_text' not in st.session_state: st.session_state.audit_text = None

user_input = st.text_input("Enter Link or Description:")
audio_file = st.file_uploader("Or Upload Audio", type=["mp3", "wav", "m4a"])

if st.button("Run Production Audit"):
    formatted_contents, temp_path, debug_log = process_input(user_input, audio_file)
    st.session_state.audit_text = get_fstrx_audit(formatted_contents)
    st.session_state.spotify_results = parse_and_search_spotify(st.session_state.audit_text)

if st.session_state.audit_text:
    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown(st.session_state.audit_text.split("###")[0])
    with col2:
        for track in (st.session_state.get('spotify_results') or []):
            st.write(f"**{track['name']}** - {track['artist']}")
            track_id = track['url'].split("/")[-1]
            st.markdown(f'<iframe src="https://open.spotify.com/embed/track/{track_id}" width="100%" height="80" frameBorder="0" allow="encrypted-media"></iframe>', unsafe_allow_html=True)

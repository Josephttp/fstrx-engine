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
import time

# --- 1. CONFIGURATION (PULLING FROM VAULT) ---
try:
    SPOTIFY_CLIENT_ID = st.secrets["SPOTIFY_CLIENT_ID"]
    SPOTIFY_CLIENT_SECRET = st.secrets["SPOTIFY_CLIENT_SECRET"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("Missing Secrets! Please add SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, and GEMINI_API_KEY to the Streamlit Secrets dashboard.")
    st.stop()

# Initialize Clients
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET))
client = genai.Client(api_key=GEMINI_API_KEY)

# --- 2. THE MASTER FSTRX PROMPT ---
SYSTEM_PROMPT = """
# FSTRX MASTER ANALYSIS PROTOCOL

### PHASE 1: DECONSTRUCTIVE LISTENING (PRE-ANALYSIS)
Before applying any filters, you MUST perform this internal audit of the audio:
1. TIMBRAL AUDIT: Identify specific synthesis (e.g., analog saws, FM bells, 808 sub-bass). 
2. CULTURAL MOTIFS: Explicitly check for regional instruments (Koto, Erhu, Taiko) or scales (Pentatonic). If detected, these define the track's DNA and override generic genre tags.
3. HYBRID MAPPING: Is this a fusion of eras? (e.g., 80s Retro + Modern Cinematic).

### PHASE 2: THE 4-FILTER MECHANICS MATRIX
[INSERT YOUR ORIGINAL 4-FILTER LOGIC HERE]

### PHASE 3: FINAL SELECTION & OUTPUT
1. Use the insights from Phase 1 to ensure sub-genre precision (e.g., "Asian-Cyberpunk Electro" instead of "Trance").
2. Select 10 tracks that match the *mechanics* identified in Phase 1 and 2.

***SYSTEM PARSING BLOCK***
After the "TOP 10 SELECTIONS" section, add a section called "### FSTRX_DATA_EXTRACT ###".
List ONLY the 10 final tracks in this exact format, one per line:
Track Name | Artist Name
"""

# --- 3. CORE LOGIC ---
def extract_audio(search_query_or_url):
    """Silently downloads audio using yt-dlp with optimized search handling."""
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
    """3-Tier Pipeline: Upload -> Spotify Preview -> YT/SC Rip -> Text Fallback"""
    contents = []
    tmp_path = None
    detected_name = ""
    detected_artist = ""
    debug_log = {"pipeline_used": "Unknown", "audio_attached": False, "error_message": "None"}
    
    if audio_file:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            tmp.write(audio_file.getvalue())
            tmp_path = tmp.name
        debug_log["pipeline_used"] = "Tier 0: Direct MP3 Upload"
    
    elif "track/" in text_input or "spotify:" in text_input:
        match = re.search(r"track/([a-zA-Z0-9]+)", text_input)
        if match:
            try:
                t_info = sp.track(match.group(1))
                detected_name, detected_artist = t_info['name'], t_info['artists'][0]['name']
                preview = t_info.get('preview_url')
                if preview:
                    res = requests.get(preview)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                        tmp.write(res.content)
                        tmp_path = tmp.name
                    debug_log["pipeline_used"] = "Tier 1: Spotify 30s Preview"
                else:
                    try:
                        tmp_path = extract_audio(f"ytsearch1:{detected_artist} {detected_name} official audio")
                        debug_log["pipeline_used"] = "Tier 2: YouTube Rip"
                    except:
                        tmp_path = extract_audio(f"scsearch1:{detected_artist} {detected_name}")
                        debug_log["pipeline_used"] = "Tier 2: SoundCloud Rip"
            except Exception as e: debug_log["error_message"] = str(e)

    # SECURE UPLOAD & POLLING LOOP
    if tmp_path and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
        try:
            uploaded = client.files.upload(file=tmp_path)
            # Wait for Google to finish processing the file (Prevents ClientError)
            while uploaded.state.name == "PROCESSING":
                time.sleep(2)
                uploaded = client.files.get(name=uploaded.name)
            
            if uploaded.state.name == "FAILED":
                raise Exception("Google File Processing Failed.")

            contents.append(uploaded)
            debug_log["audio_attached"] = True
            contents.append("Analyze this exact audio file using the FSTRX protocol. Include ### FSTRX_DATA_EXTRACT ### at the end.")
            return contents, tmp_path, debug_log
        except Exception as e:
            debug_log["error_message"] = f"Upload/Process Error: {e}"

    # Fallback to text if audio fails
    debug_log["pipeline_used"] = "Tier 3: Text Fallback"
    contents.append(f"Audio failed. Search '{detected_name}' by '{detected_artist}' to run FSTRX audit. Include ### FSTRX_DATA_EXTRACT ###.")
    return contents, None, debug_log

# --- 4. FRONTEND UI ---
st.set_page_config(page_title="FSTRX Engine", layout="wide")
st.title("FSTRX Production Supervisor Engine")
if 'audit' not in st.session_state: st.session_state.audit = None

inp = st.text_input("Enter Link or Description:")
file = st.file_uploader("Or Upload MP3", type=["mp3", "wav", "m4a"])

if st.button("Run Production Audit"):
    with st.spinner("Detective is listening and processing audio..."):
        cont, t_path, dbg = process_input(inp, file)
        st.session_state.debug = dbg
        # Generate Content with Search Tool enabled
        res = client.models.generate_content(
            model='gemini-2.0-flash', 
            contents=cont, 
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, tools=[{"google_search": {}}])
        )
        st.session_state.audit = res.text
        if t_path and os.path.exists(t_path): os.remove(t_path)

if st.session_state.audit:
    col1, col2 = st.columns([2, 1])
    with col1: 
        st.markdown(st.session_state.audit.split("###")[0])
        with st.expander("🛠️ Diagnostics"):
            st.write(st.session_state.debug)
    with col2:
        if "### FSTRX_DATA_EXTRACT ###" in st.session_state.audit:
            extract = st.session_state.audit.split("### FSTRX_DATA_EXTRACT ###")[-1].strip()
            for line in extract.split('\n'):
                if "|" in line:
                    t, a = line.split("|")
                    s = sp.search(q=f"track:{t.strip()} artist:{a.strip()}", type='track', limit=1)
                    if s['tracks']['items']:
                        tid = s['tracks']['items'][0]['id']
                        st.markdown(f'<iframe src="https://open.spotify.com/embed/track/{tid}" width="100%" height="80" frameBorder="0" allow="encrypted-media"></iframe>', unsafe_allow_html=True)

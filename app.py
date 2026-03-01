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

# --- 1. CONFIGURATION (SECURE VAULT) ---
try:
    SPOTIFY_CLIENT_ID = st.secrets["SPOTIFY_CLIENT_ID"]
    SPOTIFY_CLIENT_SECRET = st.secrets["SPOTIFY_CLIENT_SECRET"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("KEYS MISSING: Go to Streamlit Settings > Secrets and add your keys.")
    st.stop()

sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET))
client = genai.Client(api_key=GEMINI_API_KEY)

# --- 2. THE MASTER FSTRX PROMPT ---
SYSTEM_PROMPT = """
# FSTRX MASTER ANALYSIS PROTOCOL

### PHASE 1: DECONSTRUCTIVE LISTENING (PRE-ANALYSIS)
Before applying any filters, you MUST perform this internal audit of the audio:
1. TIMBRAL AUDIT: Identify specific synthesis (e.g., analog saws, FM bells, 808 sub-bass). 
2. CULTURAL MOTIFS: Explicitly check for regional instruments (Koto, Erhu, Taiko) or scales (Pentatonic). If detected, these define the track's DNA.
3. HYBRID MAPPING: Is this a fusion of eras? (e.g., 80s Retro + Modern Cinematic).

### PHASE 2: THE 4-FILTER MECHANICS MATRIX
[INSERT YOUR ORIGINAL 4-FILTER LOGIC HERE]

### PHASE 3: FINAL SELECTION & OUTPUT
1. Use the insights from Phase 1 to ensure sub-genre precision (e.g., "Asian-Cyberpunk Electro" instead of "Trance").
2. Select 10 tracks that match the mechanics identified in Phase 1 and 2.

***SYSTEM PARSING BLOCK***
After the "TOP 10 SELECTIONS" section, add a section called "### FSTRX_DATA_EXTRACT ###".
List ONLY the 10 final tracks in this exact format: Track Name | Artist Name
"""

# --- 3. CORE LOGIC ---
def extract_audio(query):
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
        info = ydl.extract_info(query, download=True)
        return ydl.prepare_filename(info if 'entries' not in info else info['entries'][0])

def process_input(text_input, audio_file):
    contents, tmp_path = [], None
    detected_name, detected_artist = "", ""
    debug = {"pipeline": "Unknown", "audio": False, "use_search": False}
    
    if audio_file:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            tmp.write(audio_file.getvalue())
            tmp_path = tmp.name
        debug["pipeline"] = "Direct Upload"
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
                    debug["pipeline"] = "Spotify Preview"
                else:
                    try:
                        tmp_path = extract_audio(f"ytsearch1:{detected_artist} {detected_name} official audio")
                        debug["pipeline"] = "Audio Rip"
                    except:
                        tmp_path = extract_audio(f"scsearch1:{detected_artist} {detected_name}")
                        debug["pipeline"] = "SoundCloud Rip"
            except Exception: pass

    if tmp_path and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
        try:
            uploaded = client.files.upload(file=tmp_path)
            while uploaded.state.name == "PROCESSING":
                time.sleep(2)
                uploaded = client.files.get(name=uploaded.name)
            contents.append(uploaded)
            debug["audio"] = True
            contents.append("Perform FSTRX audit based on this audio. Include ### FSTRX_DATA_EXTRACT ###.")
            return contents, tmp_path, debug
        except Exception: pass

    debug["pipeline"] = "Tier 3: Text Fallback"
    debug["use_search"] = True
    contents.append(f"Search for '{detected_name}' by '{detected_artist}' and run FSTRX audit. Include ### FSTRX_DATA_EXTRACT ###.")
    return contents, None, debug

# --- 4. FRONTEND UI ---
st.set_page_config(page_title="FSTRX Engine", layout="wide")
st.title("FSTRX Production Supervisor Engine")

# Maintain state for similar track searches
if 'audit_text' not in st.session_state: st.session_state.audit_text = None
if 'spotify_results' not in st.session_state: st.session_state.spotify_results = None
if 'similar_tracks' not in st.session_state: st.session_state.similar_tracks = {}

inp = st.text_input("Enter Link or Description:")
file = st.file_uploader("Or Upload MP3", type=["mp3", "wav", "m4a"])

if st.button("Run Production Audit"):
    with st.spinner("Detective is listening..."):
        st.session_state.similar_tracks = {} 
        cont, t_path, dbg = process_input(inp, file)
        st.session_state.debug = dbg
        
        config = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT)
        if dbg["use_search"]: config.tools = [{"google_search": {}}]

        res = client.models.generate_content(model='gemini-2.0-flash', contents=cont, config=config)
        st.session_state.audit_text = res.text
        
        # Parse Spotify Links
        results = []
        if "### FSTRX_DATA_EXTRACT ###" in res.text:
            extract = res.text.split("### FSTRX_DATA_EXTRACT ###")[-1].strip()
            for line in extract.split('\n'):
                if "|" in line:
                    t, a = line.split("|")
                    s = sp.search(q=f"track:{t.strip()} artist:{a.strip()}", type='track', limit=1)
                    if s['tracks']['items']:
                        results.append({"name": t.strip(), "artist": a.strip(), "id": s['tracks']['items'][0]['id']})
        st.session_state.spotify_results = results
        if t_path and os.path.exists(t_path): os.remove(t_path)

if st.session_state.audit_text:
    col1, col2 = st.columns([2, 1])
    with col1: 
        st.markdown(st.session_state.audit_text.split("###")[0])
        with st.expander("🛠️ Diagnostics"): st.write(st.session_state.debug)
    with col2:
        st.subheader("FSTRX Crate")
        for track in (st.session_state.spotify_results or []):
            st.write(f"**{track['name']}** - {track['artist']}")
            # Black Theme Player (theme=0)
            st.markdown(f'<iframe src="https://open.spotify.com/embed/track/{track["id"]}?theme=0" width="100%" height="80" frameBorder="0" allow="encrypted-media"></iframe>', unsafe_allow_html=True)
            
            # Similarity Button
            if st.button(f"🔍 Find Similar to {track['name']}", key=f"sim_{track['id']}"):
                with st.spinner(f"Finding matches for {track['name']}..."):
                    sim_inp = f"spotify:track:{track['id']}"
                    sim_cont, sim_path, sim_dbg = process_input(sim_inp, None)
                    sim_config = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT)
                    if sim_dbg["use_search"]: sim_config.tools = [{"google_search": {}}]
                    sim_res = client.models.generate_content(model='gemini-2.0

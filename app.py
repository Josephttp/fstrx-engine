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

# --- 1. CONFIGURATION ---
SPOTIFY_CLIENT_ID = "9a1311a072be4ed3bf7c21ec85faf5af"
SPOTIFY_CLIENT_SECRET = "ba38185f877e4aa7b2c298e22ac68807"
GEMINI_API_KEY = "AIzaSyCSSj6JCTLb7-gqRlN4BXeINVeJeIwdNio"

sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET))
client = genai.Client(api_key=GEMINI_API_KEY)

# --- 2. THE FSTRX PROMPT ---
SYSTEM_PROMPT = """
[INSERT YOUR ENTIRE FSTRX SYSTEM PROMPT HERE]

***SYSTEM PARSING BLOCK (DO NOT FORMAT, JUST LIST)***
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
        'ignoreerrors': False,
        'logtostderr': False,
        'no_warnings': True,
        'default_search': 'auto',
        'source_address': '0.0.0.0',
        # Fixed: Bypasses YT 403 and prevents the "Max Downloads" error on SC
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
    
    debug_log = {
        "pipeline_used": "Unknown",
        "audio_attached": False,
        "error_message": "None",
        "prompt_sent": ""
    }
    
    # TIER 0: Direct Audio File Upload
    if audio_file is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            tmp.write(audio_file.getvalue())
            tmp_path = tmp.name
        debug_log["pipeline_used"] = "Tier 0: Direct MP3 Upload"

    # TIER 1 & 2: Spotify Links
    elif "spotify.com" in text_input or "spotify:" in text_input:
        match = re.search(r"track/([a-zA-Z0-9]+)", text_input)
        if match:
            track_id = match.group(1)
            try:
                track_info = sp.track(track_id)
                detected_name = track_info['name']
                detected_artist = track_info['artists'][0]['name']
                preview_url = track_info.get('preview_url')
                
                # TIER 1: Spotify Preview API
                if preview_url:
                    response = requests.get(preview_url)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                        tmp.write(response.content)
                        tmp_path = tmp.name
                    debug_log["pipeline_used"] = "Tier 1: Spotify API 30s Preview"
                
                # TIER 2: Redundant Rip (YouTube -> SoundCloud)
                else:
                    try:
                        search_query = f"ytsearch1:{detected_artist} {detected_name} official audio"
                        tmp_path = extract_audio(search_query)
                        debug_log["pipeline_used"] = "Tier 2: YouTube Audio Rip"
                    except Exception as e_yt:
                        try:
                            sc_query = f"scsearch1:{detected_artist} {detected_name}"
                            tmp_path = extract_audio(sc_query)
                            debug_log["pipeline_used"] = "Tier 2: SoundCloud Audio Rip (YT Blocked)"
                        except Exception as e_sc:
                            debug_log["error_message"] = f"YT: {str(e_yt)} | SC: {str(e_sc)}"
            except Exception as e:
                debug_log["error_message"] = str(e)
                
    # Direct YouTube Links
    elif "youtube.com" in text_input or "youtu.be" in text_input:
        try:
            tmp_path = extract_audio(text_input)
            debug_log["pipeline_used"] = "Tier 2: Direct YouTube Rip"
        except Exception as e:
            debug_log["error_message"] = str(e)

    # --- PUSH TO LLM ---
    if tmp_path and os.path.exists(tmp_path):
        uploaded_audio = client.files.upload(file=tmp_path)
        contents.append(uploaded_audio)
        debug_log["audio_attached"] = True
        
        # Acoustic Blindfold: No metadata passed to prevent anchoring bias
        instruction = "Analyze this exact audio file using the FSTRX protocol based purely on its acoustic mechanics."
        if "[SYSTEM OVERRIDE" in text_input:
            override_text = text_input.split("[SYSTEM OVERRIDE:")[1].split("]")[0]
            instruction += f"\n\n[SYSTEM OVERRIDE: {override_text}]"
            
        instruction += "\n\nCRITICAL SYSTEM REQUIREMENT: You MUST include the ### FSTRX_DATA_EXTRACT ### list at the very end of your response."
        contents.append(instruction)
        debug_log["prompt_sent"] = instruction
        return contents, tmp_path, debug_log

    # TIER 3: The Text Fallback
    else:
        debug_log["pipeline_used"] = "Tier 3: Metadata Text Fallback (Audio Failed)"
        if detected_name and detected_artist:
            fallback_prompt = f"Audio extraction failed. You MUST search Google for the song '{detected_name}' by '{detected_artist}' to find its 'Genre', 'BPM', 'Key', 'Production Credits', and 'Reviews'. Use that text data to run the FSTRX audit. User Notes: {text_input}"
        else:
            fallback_prompt = f"Analyze this request using Google Search and the FSTRX protocol: {text_input}"
            
        fallback_prompt += "\n\nCRITICAL SYSTEM REQUIREMENT: You MUST include the ### FSTRX_DATA_EXTRACT ### list at the very end of your response."
        contents.append(fallback_prompt)
        debug_log["prompt_sent"] = fallback_prompt
        return contents, None, debug_log

def get_fstrx_audit(formatted_contents):
    response = client.models.generate_content(
        model='gemini-2.5-pro',
        contents=formatted_contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.6, 
            max_output_tokens=8192,
            tools=[{"google_search": {}}]
        )
    )
    return response.text

def parse_and_search_spotify(llm_text):
    spotify_tracks = []
    if "### FSTRX_DATA_EXTRACT ###" in llm_text:
        extraction_block = llm_text.split("### FSTRX_DATA_EXTRACT ###")[1]
        extraction_block = extraction_block.replace("```text", "").replace("```", "").strip()
        lines = extraction_block.split('\n')
        for line in lines:
            if "|" in line:
                parts = line.split("|")
                raw_track = parts[0].strip()
                raw_artist = parts[1].strip()
                clean_track = re.sub(r'^[\d\.\-\*\s]+', '', raw_track).replace('"', '')
                clean_artist = raw_artist.replace('"', '')
                query = f"track:{clean_track} artist:{clean_artist}"
                try:
                    result = sp.search(q=query, type='track', limit=1)
                    tracks = result['tracks']['items']
                    if tracks:
                        t = tracks[0]
                        spotify_tracks.append({
                            "name": t['name'],
                            "artist": t['artists'][0]['name'],
                            "url": t['external_urls']['spotify'],
                            "image": t['album']['images'][0]['url'] if t['album']['images'] else None
                        })
                except Exception:
                    pass 
    return spotify_tracks

# --- 4. FRONTEND UI ---
st.set_page_config(page_title="FSTRX Engine", layout="wide")
st.title("FSTRX Production Supervisor Engine")

if 'audit_text' not in st.session_state:
    st.session_state.audit_text = None
if 'spotify_results' not in st.session_state:
    st.session_state.spotify_results = None
if 'similar_tracks' not in st.session_state:
    st.session_state.similar_tracks = {} 
if 'diagnostic_log' not in st.session_state:
    st.session_state.diagnostic_log = None

st.markdown("### Reference Input")

user_input = st.text_input("Enter YouTube Link, Spotify Link, or Text Description:", key="fstrx_main_input")
st.markdown("**OR**")
audio_file = st.file_uploader("Upload an Audio File (MP3, WAV, M4A)", type=["mp3", "wav", "m4a"], key="fstrx_audio_upload")

if st.button("Run Production Audit", key="run_main_audit"):
    if user_input or audio_file:
        st.session_state.similar_tracks = {} 
        with st.spinner("Processing input and analyzing FSTRX matrix..."):
            formatted_contents, temp_audio_path, debug_log = process_input(user_input, audio_file)
            st.session_state.diagnostic_log = debug_log
            st.session_state.audit_text = get_fstrx_audit(formatted_contents)
            
            if temp_audio_path and os.path.exists(temp_audio_path):
                try:
                    os.remove(temp_audio_path)
                except Exception:
                    pass
            st.toast("Fetching FSTRX Crate from Spotify...")
            st.session_state.spotify_results = parse_and_search_spotify(st.session_state.audit_text)
    else:
        st.warning("Please provide a link, text, or an audio file.")

if st.session_state.audit_text is not None:
    display_text = st.session_state.audit_text.split("### FSTRX_DATA_EXTRACT ###")[0]
    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("Production Audit")
        st.markdown(display_text)
        if st.session_state.diagnostic_log:
            with st.expander("🛠️ FSTRX Engine Diagnostics (Under the Hood)"):
                st.markdown(f"**Pipeline:** {st.session_state.diagnostic_log['pipeline_used']}")
                st.markdown(f"**Audio Sent:** {st.session_state.diagnostic_log['audio_attached']}")
                if st.session_state.diagnostic_log["error_message"] != "None":
                    st.error(f"Error: {st.session_state.diagnostic_log['error_message']}")
                st.text(f"Prompt: {st.session_state.diagnostic_log['prompt_sent']}")
    with col2:
        st.subheader("FSTRX Crate")
        for track in (st.session_state.spotify_results or []):
            track_id = track['url'].split("/")[-1].split("?")[0]
            iframe_html = f'<iframe style="border-radius:12px" src="https://open.spotify.com/embed/track/{track_id}?theme=0" width="100%" height="152" frameBorder="0" allowfullscreen="" allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture" loading="lazy"></iframe>'
            st.write(f"**{track['name']}** - {track['artist']}")
            st.markdown(iframe_html, unsafe_allow_html=True)
            if st.button(f"🔍 Find 5 Similar Tracks", key=f"btn_sim_{track_id}"):
                with st.spinner(f"Running similarity audit for {track['name']}..."):
                    sim_input = f"{track['url']} \n\n[SYSTEM OVERRIDE: Perform the exact same FSTRX audit on this track, but return EXACTLY 5 high-precision matches instead of 10.]"
                    sim_contents, temp_sim_audio_path, _ = process_input(sim_input, None)
                    sim_audit = get_fstrx_audit(sim_contents)
                    if temp_sim_audio_path and os.path.exists(temp_sim_audio_path):
                        try:
                            os.remove(temp_sim_audio_path)
                        except Exception:
                            pass
                    st.session_state.similar_tracks[track_id] = parse_and_search_spotify(sim_audit)
            if track_id in st.session_state.similar_tracks:
                st.markdown("#### ↳ 5 Similar Tracks:")
                for sim_track in st.session_state.similar_tracks[track_id]:
                    sim_id = sim_track['url'].split("/")[-1].split("?")[0]
                    sim_iframe = f'<iframe style="border-radius:12px" src="https://open.spotify.com/embed/track/{sim_id}?theme=0" width="100%" height="152" frameBorder="0" allowfullscreen="" allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture" loading="lazy"></iframe>'
                    st.markdown(sim_iframe, unsafe_allow_html=True)
            st.divider()
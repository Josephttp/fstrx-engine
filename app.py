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
Track

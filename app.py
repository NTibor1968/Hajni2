import streamlit as st
import requests
from anthropic import Anthropic

# Kulcsok betöltése és letisztítása a TOML írásjelektől
try:
    SUPABASE_URL = str(st.secrets["SUPABASE_URL"]).strip().strip("'").strip('"')
    SUPABASE_KEY = str(st.secrets["SUPABASE_KEY"]).strip().strip("'").strip('"')
    ANTHROPIC_API_KEY = str(st.secrets["ANTHROPIC_API_KEY"]).strip().strip("'").strip('"')
except Exception as e:
    st.error("Hiba! Hiányzik a secrets.toml vagy hibásak a kulcsok.")
    st.stop()

# Anthropic kliens indítása
claude_client = Anthropic(api_key=ANTHROPIC_API_KEY)

# Supabase hálózati fejléc beállítása
headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

st.set_page_config(page_title="Hajni2 Asszisztens", layout="wide")
st.title("🤖 Hajni2 AI Munkaállomás")

# --- PROJEKTEK LEKÉRÉSE ---
active_projects = []
try:
    url = f"{SUPABASE_URL}/rest/v1/projects?status=eq.active&order=created_at.desc"
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        active_projects = res.json()
except Exception:
    pass

# --- OLDALSÁV (SIDEBAR) ---
with st.sidebar:
    st.header("🗂️ Projektek")
    new_project_name = st.text_input("Új téma / projekt neve:", key="new_proj_input")
    
    if st.button("➕ Projekt létrehozása", use_container_width=True):
        if new_project_name.strip():
            post_url = f"{SUPABASE_URL}/rest/v1/projects"
            requests.post(post_url, headers=headers, json={"name": new_project_name.strip(), "status": "active"})
            st.rerun()

    st.divider()
    
    if active_projects:
        st.subheader("Aktív ügyek")
        project_options = {p["name"]: p["id"] for p in active_projects if "name" in p}
        valasztott_nev = st.radio("Válassz projektet:", list(project_options.keys()))
        current_project_id = project_options[valasztott_nev] if valasztott_nev else None
    else:
        st.info("Nincs aktív projekt. Hozz létre egyet fent!")
        current_project_id = None

# --- FŐKÉPERNYŐ ---
if current_project_id:
    st.write(f"### 🎯 Kiválasztott ügy: {valasztott_nev}")
    st.success("Adatbázis kapcsolat aktív! Készen áll a használatra.")
else:
    st.write("### 👈 Kezdéshez válassz vagy hozz létre egy projektet a bal oldali sávban!")

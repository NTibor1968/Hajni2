import streamlit as st
import requests
import json
from anthropic import Anthropic

# Kulcsok betöltése és drasztikus letisztítása (eltávolítjuk a TOML idézőjeleket és aposztrófokat)
try:
    SUPABASE_URL = str(st.secrets["SUPABASE_URL"]).strip().strip("'").strip('"')
    SUPABASE_KEY = str(st.secrets["SUPABASE_KEY"]).strip().strip("'").strip('"')
    ANTHROPIC_API_KEY = str(st.secrets["ANTHROPIC_API_KEY"]).strip().strip("'").strip('"')
except Exception as e:
    st.error("Hiba! Hiányzik a secrets.toml vagy hibásak a kulcsok.")
    st.stop()

# Anthropic kliens inicializálása a tiszta kulccsal
claude_client = Anthropic(api_key=ANTHROPIC_API_KEY)

# Supabase kézi fejléc tisztán, nyers szövegként
headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

st.set_page_config(page_title="Hajni2 Asszisztens", layout="wide")

# --- KÉZI ADATBÁZIS MŰVELETEK (HIBAKEZELÉSSEL) ---
def get_projects(status="active"):
    try:
        url = f"{SUPABASE_URL}/rest/v1/projects?status=eq.{status}&order=created_at.desc"
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            st.sidebar.error(f"Hiba az adatok lekérésekor: {response.status_code}")
            return []
    except Exception as e:
        st.sidebar.error(f"Kapcsolódási hiba: {e}")
        return []

def create_project(name):
    if name.strip():
        url = f"{SUPABASE_URL}/rest/v1/projects"
        data = {"name": name, "status": "active"}
        response = requests.post(url, headers=headers, json=data)
        if response.status_code in:
            st.success(f"Projekt sikeresen létrehozva!")
            st.rerun()
        else:
            st.error(f"Nem sikerült menteni a Supabase-be. Kód: {response.status_code}, Válasz: {response.text}")

def archive_project(project_id):
    url = f"{SUPABASE_URL}/rest/v1/projects?id=eq.{project_id}"
    data = {"status": "archived"}
    requests.patch(url, headers=headers, json=data)
    st.rerun()

def get_messages(project_id):
    try:
        url = f"{SUPABASE_URL}/rest/v1/messages?project_id=eq.{project_id}&order=created_at.asc"
        response = requests.get(url, headers=headers)
        return response.json() if response.status_code == 200 else []
    except Exception:
        return []

def save_message(project_id, role, content):
    url = f"{SUPABASE_URL}/rest/v1/messages"
    data = {"project_id": project_id, "role": role, "content": content}
    requests.post(url, headers=headers, json=data)

# --- FELHASZNÁLÓI FELÜLET (UI) ---
st.title("🤖 Hajni2 AI Munkaállomás")

with st.sidebar:
    st.header("🗂️ Projektek")
    new_project_name = st.text_input("Új téma / projekt neve:", key="new_proj_input")
    if st.button("➕ Projekt létrehozása", use_container_width=True):
        create_project(new_project_name)
    st.divider()
    
    active_projektek = get_projects("active")
    if active_projektek and isinstance(active_projektek, list):
        st.subheader("Aktív ügyek")
        project_options = {p["name"]: p["id"] for p in active_projektek if "name" in p}
        valasztott_nev = st.radio("Válassz projektet:", list(project_options.keys()))
        current_project_id = project_options[valasztott_nev] if valasztott_nev else None
    else:
        st.info("Nincs aktív projekt. Hozz létre egyet fent!")
        current_project_id = None
    st.divider()
    if current_project_id:
        if st.button("📦 Kiválasztott projekt archiválása", type="secondary", use_container_width=True):
            archive_project(current_project_id)

if current_project_id:
    tab_chat, tab_docs, tab_diagrams = st.tabs(["💬 Beszélgetés", "📄 Dokumentumok", "📊 Folyamatábrák"])
    with tab_chat:
        st.subheader(f"Folyamatban lévő ügy: {valasztott_nev}")
        messages = get_messages(current_project_id)
        if messages and isinstance(messages, list):
            for msg in messages:
                if "role" in msg and "content" in msg:
                    with st.chat_message(msg["role"]):
                        st.write(msg["content"])
        
        if user_input := st.chat_input("Kérdezz, elemezzünk törvényt..."):
            with st.chat_message("user"):
                st.write(user_input)
            save_message(current_project_id, "user", user_input)
            
            context_messages = []
            if messages and isinstance(messages, list):
                context_messages = [{"role": m["role"], "content": m["content"]} for m in messages if "role" in m]
            context_messages.append({"role": "user", "content": user_input})
            
            with st.chat_message("assistant"):
                with st.spinner("Hajni gondolkodik..."):
                    response = claude_client.messages.create(
                        model="claude-3-5-sonnet-20241022",
                        max_tokens=4000,
                        messages=context_messages
                    )
                    answer = response.content.text
                    st.write(answer)
            save_message(current_project_id, "assistant", answer)
            st.rerun()
    with tab_docs:
        st.subheader("Feltöltött anyagok")
        uploaded_file = st.file_uploader("Fájlok csatolása:", type=["txt", "pdf", "docx"])
    with tab_diagrams:
        st.subheader("Generált folyamatábrák")
else:
    st.write("### 👈 Kezdéshez válassz vagy hozz létre egy projektet a bal oldali sávban!")

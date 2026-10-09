import streamlit as st
import requests
import base64
from anthropic import Anthropic

# Kényszerített oldal konfiguráció a legelső sorban
st.set_page_config(page_title="Piri Asszisztens", layout="wide")

# Kulcsok biztonságos betöltése a Streamlit felhőből (Nem a kódból!)
try:
    SUPABASE_URL = str(st.secrets["SUPABASE_URL"]).strip().strip("'").strip('"')
    SUPABASE_KEY = str(st.secrets["SUPABASE_KEY"]).strip().strip("'").strip('"')
    ANTHROPIC_API_KEY = str(st.secrets["ANTHROPIC_API_KEY"]).strip().strip("'").strip('"')
except Exception as e:
    st.error("Hiba! Hiányzik a Secrets konfiguráció a Streamlit felületén.")
    st.stop()

# Kliens indítása
claude_client = Anthropic(api_key=ANTHROPIC_API_KEY)

# Supabase hálózati fejléc
headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

st.title("🤖 Piri AI Munkaállomás")

# --- ADATBÁZIS MŰVELETEK ---
def get_projects(status="active"):
    try:
        url = f"{SUPABASE_URL}/rest/v1/projects?status=eq.{status}&order=created_at.desc"
        res = requests.get(url, headers=headers)
        return res.json() if res.status_code == 200 else []
    except Exception:
        return []

def create_project(name):
    if name.strip():
        url = f"{SUPABASE_URL}/rest/v1/projects"
        requests.post(url, headers=headers, json={"name": name.strip(), "status": "active"})
        st.rerun()

def get_messages(project_id):
    try:
        url = f"{SUPABASE_URL}/rest/v1/messages?project_id=eq.{project_id}&order=created_at.asc"
        res = requests.get(url, headers=headers)
        return res.json() if res.status_code == 200 else []
    except Exception:
        return []

def save_message(project_id, role, content):
    url = f"{SUPABASE_URL}/rest/v1/messages"
    requests.post(url, headers=headers, json={"project_id": project_id, "role": role, "content": content})

# --- OLDALSÁV (SIDEBAR) ---
with st.sidebar:
    st.header("🗂️ Projektek")
    
    with st.form("project_form", clear_on_submit=True):
        new_project_name = st.text_input("Új téma / projekt neve:")
        submit_button = st.form_submit_button("➕ Projekt létrehozása", use_container_width=True)
        if submit_button and new_project_name.strip():
            create_project(new_project_name)

    st.divider()
    
    active_projects = get_projects("active")
    if active_projects:
        st.subheader("Aktív ügyek")
        project_options = {p["name"]: p["id"] for p in active_projects if "name" in p}
        valasztott_nev = st.radio("Válassz projektet:", list(project_options.keys()))
        current_project_id = project_options[valasztott_nev] if valasztott_nev else None
    else:
        st.info("Nincs aktív projekt.")
        current_project_id = None

# --- FŐKÉPERNYŐ CHAT ÉS FÁJLKEZELŐ FUNKCIÓVAL ---
if current_project_id:
    tab_chat, tab_docs, tab_diagrams = st.tabs(["💬 Beszélgetés", "📄 Dokumentumok és Képek csatolása", "📊 Folyamatábrák"])
    
    with tab_docs:
        st.subheader("📁 Anyagok csatolása a munkához")
        st.write("Feltölthetsz dokumentumokat (TXT) vagy képernyőképeket (PNG, JPG), amelyeket Piri elemezni fog.")
        
        uploaded_file = st.file_uploader("Válassz fájlt vagy képet:", type=["txt", "png", "jpg", "jpeg"], key="workspace_uploader")
        
        if uploaded_file:
            st.info(f"📎 Csatolva: {uploaded_file.name} ({uploaded_file.type})")
            if "image" in uploaded_file.type:
                st.image(uploaded_file, caption="Feltöltött képernyőkép előnézete")
    
    with tab_chat:
        st.subheader(f"Folyamatban lévő ügy: {valasztott_nev}")
        
        messages = get_messages(current_project_id)
        if messages and isinstance(messages, list):
            for msg in messages:
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])
        
        if user_input := st.chat_input("Kérdezz Piritól, vagy kérj elemzést a csatolt fájlra..."):
            with st.chat_message("user"):
                st.write(user_input)
            
            save_message(current_project_id, "user", user_input)
            
            api_messages = []
            if messages and isinstance(messages, list):
                api_messages = [{"role": m["role"], "content": m["content"]} for m in messages if "role" in m]
            
            current_content = []
            
            # Képkezelés Base64 formátumban
            if uploaded_file and "image" in uploaded_file.type:
                file_bytes = uploaded_file.read()
                base64_image = base64.b64encode(file_bytes).decode("utf-8")
                
                current_content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": uploaded_file.type,
                        "data": base64_image
                    }
                })
            
            # Szöveges fájl csatolása
            elif uploaded_file and "text" in uploaded_file.type:
                string_data = uploaded_file.read().decode("utf-8")
                user_input = f"[Mellékelt fájl tartalma ({uploaded_file.name}):\n{string_data}]\n\n{user_input}"
            
            current_content.append({
                "type": "text",
                "text": user_input
            })
            
            api_messages.append({"role": "user", "content": current_content})
            
            # SYSTEM PROMPT A GYÖNYÖRŰ MAGYAR JOGI NYELVÉRT (SOHA LE NEM JÁRÓ MODELLHEZ)
            system_instruction = (
                "Te egy professzionális, rendkívül intelligens és precíz jogi és törvényelemző AI asszisztens vagy, "
                "akit Piritának (vagy röviden Pirinek) hívnak. Feladatod, hogy a felhasználót maximális szakértelemmel, "
                "részletesen, ugyanakkor teljesen érthetően segítsd az adózási, vállalkozási és bonyolult jogi ügyekben.\n"
                "Képes vagy képek, képernyőképek és dokumentumok elemzésére is. Ha a felhasználó képet küld, "
                "elemezd azt tűpontosan és válaszolj a kérdéseire.\n\n"
                "KÖTELEZŐEN BETARTANDÓ SZABÁLYOK:\n"
                "1. Kizárólag tökéletes, érett, szakmailag hiteles és nyelvtanilag teljesen hibátlan MAGYAR nyelven válaszolj!\n"
                "2. Kerüld a tükörfordításokat és az angolos, mesterkélt kifejezéseket. Fogalmazz úgy, mint egy tapasztalt hazai tanácsadó.\n"
                "3. A válaszaid legyenek alaposak és strukturáltak. Használj vastag betűs kiemeléseket és listákat.\n"
                "4. Ne siesd el a választ, fejtsd ki részletesen a pontokat!"
            )
            
            with st.chat_message("assistant"):
                with st.spinner("Piri elemzi a tartalmat és gondolkodik..."):
                    response = claude_client.messages.create(
                        model="claude-3-5-sonnet-latest", # A felhőben ez a név tökéletesen le fut!
                        max_tokens=4000,
                        system=system_instruction,
                        messages=api_messages
                    )
                    
                    answer = response.content[0].text
            
            save_message(current_project_id, "assistant", answer)
            st.rerun()
            
    with tab_diagrams:
        st.subheader("Generált folyamatábrák")
else:
    st.write("### 👈 Kezdéshez válassz vagy hozz létre egy projektet a bal oldali sávban!")

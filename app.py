import streamlit as st
import requests
import base64
from datetime import date
from anthropic import Anthropic

# Kényszerített oldal konfiguráció a legelső sorban
st.set_page_config(page_title="Piri Asszisztens", layout="wide")

# --- KULCSOK BIZTONSÁGOS BETÖLTÉSE ---
try:
    SUPABASE_URL = str(st.secrets["SUPABASE_URL"]).strip().strip("'").strip('"')
    SUPABASE_KEY = str(st.secrets["SUPABASE_KEY"]).strip().strip("'").strip('"')
    ANTHROPIC_API_KEY = str(st.secrets["ANTHROPIC_API_KEY"]).strip().strip("'").strip('"')
except Exception as e:
    st.error("Hiba! Hiányzik a Secrets konfiguráció a Streamlit felületén.")
    st.stop()

# --- ATOMBIZTOS UK-TISZTÍTÁS ÉS INICIALIZÁLÁS ---
# A legfrissebb Secrets-ből beolvasott tiszta kulccsal indítjuk el a klienst
clean_key = str(ANTHROPIC_API_KEY).strip().replace("'", "").replace('"', '')
claude_client = Anthropic(api_key=clean_key)

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
        st.write("Feltölthetsz dokumentumokat (TXT, PDF) vagy képernyőképeket (PNG, JPG), amelyeket Piri elemezni fog.")

        uploaded_files = st.file_uploader("Válassz fájlokat vagy képeket:", type=["txt", "pdf", "png", "jpg", "jpeg"], accept_multiple_files=True, key="workspace_uploader")

        for uploaded_file in uploaded_files:
            st.info(f"📎 Csatolva: {uploaded_file.name} ({uploaded_file.type})")
            if "image" in uploaded_file.type:
                st.image(uploaded_file, caption=f"Előnézet: {uploaded_file.name}")
    
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
            text_attachments = []

            for uploaded_file in uploaded_files:
                # Képkezelés Base64 formátumban
                if "image" in uploaded_file.type:
                    base64_image = base64.b64encode(uploaded_file.getvalue()).decode("utf-8")

                    current_content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": uploaded_file.type,
                            "data": base64_image
                        }
                    })

                # PDF dokumentum csatolása Base64 formátumban
                elif uploaded_file.type == "application/pdf":
                    base64_pdf = base64.b64encode(uploaded_file.getvalue()).decode("utf-8")

                    current_content.append({
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": base64_pdf
                        },
                        "title": uploaded_file.name
                    })

                # Szöveges fájl csatolása
                elif "text" in uploaded_file.type:
                    string_data = uploaded_file.getvalue().decode("utf-8")
                    text_attachments.append(f"[Mellékelt fájl tartalma ({uploaded_file.name}):\n{string_data}]")

            if text_attachments:
                user_input = "\n\n".join(text_attachments) + f"\n\n{user_input}"

            current_content.append({
                "type": "text",
                "text": user_input
            })
            
            api_messages.append({"role": "user", "content": current_content})
            
            # SYSTEM PROMPT A GYÖNYÖRŰ MAGYAR JOGI NYELVÉRT
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
                "4. Ne siesd el a választ, fejtsd ki részletesen a pontokat!\n\n"
                "INTERNETES KERESÉS:\n"
                f"A mai dátum: {date.today().isoformat()}. Van internetes keresési lehetőséged. "
                "A tudásod egy jóval korábbi időpontig tart, ezért a hatályos jogszabályokra, adómértékekre, határidőkre, "
                "díjakra, hatósági szabályokra és minden aktuális adatra keress rá, mielőtt válaszolsz, még ha biztosnak is érzed magad. "
                "Magyar jogi és adózási kérdésekben elsősorban hivatalos forrásokat használj (pl. njt.hu, nav.gov.hu, magyarkozlony.hu). "
                "A válaszban jelöld meg, mely forrásokra támaszkodtál."
            )

            # Beépített webes kereső eszköz (az Anthropic szerverein fut)
            tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]

            with st.chat_message("assistant"):
                with st.spinner("Piri elemzi a tartalmat, keres és gondolkodik..."):
                    answer_parts = []
                    sources = {}

                    # A szerveroldali keresés megszakadhat (pause_turn), ilyenkor folytatjuk a választ
                    for _ in range(3):
                        response = claude_client.messages.create(
                            model="claude-haiku-5-5",  # A Claude Haiku 3.5 2026.02.19-én kivezetésre került
                            max_tokens=16000,
                            system=system_instruction,
                            messages=api_messages,
                            tools=tools
                        )

                        # Az új modellek gondolkodási (thinking) és keresési blokkot is visszaadhatnak, ezért csak a szöveges blokkokat vesszük
                        for block in response.content:
                            if block.type == "text":
                                answer_parts.append(block.text)
                                for citation in block.citations or []:
                                    if getattr(citation, "url", None):
                                        sources[citation.url] = citation.title or citation.url

                        if response.stop_reason != "pause_turn":
                            break
                        api_messages.append({"role": "assistant", "content": response.content})

                    answer = "".join(answer_parts)
                    if sources:
                        answer += "\n\n**Források:**\n" + "\n".join(f"- [{title}]({url})" for url, title in sources.items())
                    st.write(answer)
            
            save_message(current_project_id, "assistant", answer)
            st.rerun()
            
    with tab_diagrams:
        st.subheader("Generált folyamatábrák")
else:
    st.write("### 👈 Kezdéshez válassz vagy hozz létre egy projektet a bal oldali sávban!")

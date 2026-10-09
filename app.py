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

# --- DOKUMENTUMTÁR MŰVELETEK (projektenként) ---
MAX_FILE_MB = 10  # a tartalom Base64-ként az adatbázisban tárolódik, ezért korlátozzuk a méretet

def get_documents(project_id):
    """Az adott projekt dokumentumainak listája (tartalom nélkül)."""
    try:
        url = (f"{SUPABASE_URL}/rest/v1/project_documents?project_id=eq.{project_id}"
               "&select=id,name,mime_type,size_bytes,created_at&order=created_at.desc")
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            return res.json()
        st.warning(f"A dokumentumlista nem tölthető be ({res.status_code}): {res.text[:200]}")
    except Exception as e:
        st.warning(f"A dokumentumlista nem tölthető be: {e}")
    return []

def save_document(project_id, uploaded_file):
    payload = {
        "project_id": project_id,
        "name": uploaded_file.name,
        "mime_type": uploaded_file.type,
        "size_bytes": uploaded_file.size,
        "content_b64": base64.b64encode(uploaded_file.getvalue()).decode("utf-8"),
    }
    try:
        # return=minimal: ne küldje vissza a teljes (nagy) sort
        res = requests.post(f"{SUPABASE_URL}/rest/v1/project_documents",
                            headers={**headers, "Prefer": "return=minimal"}, json=payload)
        return res.status_code in (200, 201, 204), res.text[:150]
    except Exception as e:
        return False, str(e)

@st.cache_data(show_spinner=False, max_entries=10)
def get_document_content(doc_id):
    """Egy dokumentum Base64 tartalma (a dokumentumok nem módosulnak, ezért gyorsítótárazható)."""
    res = requests.get(f"{SUPABASE_URL}/rest/v1/project_documents?id=eq.{doc_id}&select=content_b64", headers=headers)
    rows = res.json() if res.status_code == 200 else []
    if not rows:
        raise RuntimeError("A dokumentum nem található.")
    return rows[0]["content_b64"]

def delete_document(doc_id):
    try:
        res = requests.delete(f"{SUPABASE_URL}/rest/v1/project_documents?id=eq.{doc_id}",
                              headers={**headers, "Prefer": "return=minimal"})
        return res.status_code in (200, 204)
    except Exception:
        return False

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
    # A projekt saját dokumentumtára (itt csak a metaadatok; a tartalom igény szerint töltődik be)
    project_docs = get_documents(current_project_id)
    docs_by_id = {d["id"]: d for d in project_docs}

    tab_chat, tab_docs, tab_diagrams = st.tabs(["💬 Beszélgetés", "📄 Dokumentumok és Képek csatolása", "📊 Folyamatábrák"])

    with tab_docs:
        st.subheader(f"📁 A(z) „{valasztott_nev}” projekt dokumentumtára")
        st.write("Az itt tárolt dokumentumok (TXT, PDF) és képek (PNG, JPG) kizárólag ehhez a projekthez tartoznak, más projektben nem jelennek meg.")

        flash = st.session_state.pop("docs_flash", None)
        if flash:
            getattr(st, flash[0])(flash[1])

        # A kulcsban lévő számláló nullázza a feltöltőt mentés után, így nem mentjük el kétszer ugyanazt
        nonce = st.session_state.get("uploader_nonce", {}).get(current_project_id, 0)
        uploaded_files = st.file_uploader(
            "Válassz fájlokat vagy képeket:",
            type=["txt", "pdf", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key=f"uploader_{current_project_id}_{nonce}",
        )

        if uploaded_files and st.button("💾 Feltöltés a projekt dokumentumtárába", type="primary"):
            saved, failed = 0, []
            for f in uploaded_files:
                if f.size > MAX_FILE_MB * 1024 * 1024:
                    failed.append(f"{f.name} (nagyobb, mint {MAX_FILE_MB} MB)")
                    continue
                ok, detail = save_document(current_project_id, f)
                if ok:
                    saved += 1
                else:
                    failed.append(f"{f.name} ({detail})")
            if failed:
                msg = "Nem sikerült feltölteni: " + "; ".join(failed) + "."
                if saved:
                    msg += f" Sikeresen feltöltve: {saved} fájl."
                st.session_state["docs_flash"] = ("error", msg)
            else:
                st.session_state["docs_flash"] = ("success", f"{saved} fájl feltöltve a projekthez.")
            st.session_state.setdefault("uploader_nonce", {})[current_project_id] = nonce + 1
            st.rerun()

        st.divider()
        if not project_docs:
            st.info("Ebben a projektben még nincs dokumentum.")
        for doc in project_docs:
            is_image = doc["mime_type"].startswith("image/")
            col_info, col_prev, col_del = st.columns([6, 2, 1])
            size_kb = max(1, round((doc.get("size_bytes") or 0) / 1024))
            col_info.write(f"{'🖼️' if is_image else '📄'} **{doc['name']}** · {size_kb} KB · {str(doc.get('created_at', ''))[:10]}")
            if is_image and col_prev.checkbox("Előnézet", key=f"prev_{doc['id']}"):
                try:
                    st.image(base64.b64decode(get_document_content(doc["id"])), caption=doc["name"], width=400)
                except Exception:
                    st.warning("Az előnézet nem tölthető be.")
            if col_del.button("🗑️", key=f"del_{doc['id']}", help="Dokumentum törlése a projektből"):
                if delete_document(doc["id"]):
                    st.rerun()
                else:
                    st.error("A törlés nem sikerült.")
    
    with tab_chat:
        st.subheader(f"Folyamatban lévő ügy: {valasztott_nev}")

        # Melyik projekt-dokumentumokat vegye figyelembe Piri (alapból mindet)
        selected_doc_ids = []
        if project_docs:
            with st.expander(f"📎 Piri számára csatolt dokumentumok ({len(project_docs)} a projektben)"):
                doc_ids = [d["id"] for d in project_docs]
                selected_doc_ids = st.multiselect(
                    "Ezeket veszi figyelembe Piri a következő kérdésnél:",
                    options=doc_ids,
                    default=doc_ids,
                    format_func=lambda i: docs_by_id[i]["name"],
                    key=f"ctx_{current_project_id}_{'_'.join(map(str, doc_ids))}",
                )
        
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

            # Csak az aktuális projekt dokumentumai kerülhetnek a kérdés mellé
            for doc_id in selected_doc_ids:
                doc = docs_by_id.get(doc_id)
                if not doc:
                    continue
                try:
                    b64_data = get_document_content(doc_id)
                except Exception:
                    st.error(f"A(z) {doc['name']} dokumentum nem tölthető be, ezért nem csatoltam.")
                    continue
                mime = doc["mime_type"]

                # Képkezelés Base64 formátumban
                if mime.startswith("image/"):
                    current_content.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": mime, "data": b64_data}
                    })

                # PDF dokumentum csatolása Base64 formátumban
                elif mime == "application/pdf":
                    current_content.append({
                        "type": "document",
                        "source": {"type": "base64", "media_type": "application/pdf", "data": b64_data},
                        "title": doc["name"]
                    })

                # Szöveges fájl csatolása
                elif mime.startswith("text/"):
                    string_data = base64.b64decode(b64_data).decode("utf-8", errors="replace")
                    text_attachments.append(f"[Mellékelt fájl tartalma ({doc['name']}):\n{string_data}]")

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

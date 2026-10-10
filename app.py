import streamlit as st
import requests
import base64
import re
from datetime import date, datetime
from anthropic import Anthropic

import chat_flow
import export_tools as ex

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

def save_document_bytes(project_id, name, mime_type, data):
    payload = {
        "project_id": project_id,
        "name": name,
        "mime_type": mime_type,
        "size_bytes": len(data),
        "content_b64": base64.b64encode(data).decode("utf-8"),
    }
    try:
        # return=minimal: ne küldje vissza a teljes (nagy) sort
        res = requests.post(f"{SUPABASE_URL}/rest/v1/project_documents",
                            headers={**headers, "Prefer": "return=minimal"}, json=payload)
        if res.status_code in (200, 201, 204):
            return True, ""
        if "42501" in res.text or "row-level security" in res.text:
            return False, ("a Supabase jogosultsági szabálya (RLS) elutasította a mentést: a project_documents "
                           "táblához hiányzik az írást engedélyező policy.")
        return False, f"{res.status_code}: {res.text[:300]}"
    except Exception as e:
        return False, str(e)

def save_document(project_id, uploaded_file):
    return save_document_bytes(project_id, uploaded_file.name, uploaded_file.type, uploaded_file.getvalue())

@st.cache_data(show_spinner=False, max_entries=20)
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

@st.cache_data(show_spinner=False, max_entries=20)
def export_markdown(doc_id, fmt, title):
    """A Piri által készített Markdown dokumentum átalakítása Word vagy PDF formátumra."""
    text = base64.b64decode(get_document_content(doc_id)).decode("utf-8", errors="replace")
    return ex.markdown_to_docx(text, title) if fmt == "docx" else ex.markdown_to_pdf(text, title)

def is_markdown_doc(doc):
    return doc["mime_type"] == ex.MD_MIME or doc["name"].lower().endswith(".md")

def render_downloads(doc, key_prefix=""):
    """Letöltőgombok egy dokumentumhoz (a tartalom csak itt, igény szerint töltődik be).
    A key_prefix azért kell, mert ugyanaz a dokumentum a chatben és a Dokumentumok fülön is megjelenhet."""
    try:
        data = base64.b64decode(get_document_content(doc["id"]))
    except Exception:
        st.warning("A dokumentum nem tölthető be.")
        return
    base_name = doc["name"].rsplit(".", 1)[0]
    is_md = is_markdown_doc(doc)
    cols = st.columns(3 if is_md else 1)
    cols[0].download_button(f"⬇️ {doc['name']}", data=data, file_name=doc["name"],
                            mime=doc["mime_type"], key=f"{key_prefix}dlb_{doc['id']}")
    if is_md:
        for col, (label, fmt, mime) in zip(cols[1:], (("⬇️ Word (.docx)", "docx", ex.DOCX_MIME),
                                                      ("⬇️ PDF", "pdf", ex.PDF_MIME))):
            try:
                col.download_button(label, data=export_markdown(doc["id"], fmt, base_name),
                                    file_name=f"{base_name}.{fmt}", mime=mime,
                                    key=f"{key_prefix}dlb_{fmt}_{doc['id']}")
            except Exception as e:
                col.warning(f"A(z) {fmt.upper()} nem készíthető el: {e}")

# --- A CHATBEN KÉSZÜLT FÁJLOK NYOMON KÖVETÉSE ---
# Ezeket a sorokat az alkalmazás fűzi Piri válasza alá (nem Piri írja).
CREATED_MARK = "📎 **Elkészült:**"
PROBLEM_MARK = "⚠️ **Figyelem:**"

def created_names(content):
    """Az üzenet alá fűzött „Elkészült” sorból a fájlnevek."""
    for line in str(content).splitlines():
        if line.startswith(CREATED_MARK):
            return list(dict.fromkeys(re.findall(r"`([^`]+)`", line)))
    return []

def strip_app_notes(content):
    """Az alkalmazás által hozzáfűzött sorok nélkül adjuk vissza a választ Pirinek, különben utánozni kezdi
    őket: „Elkészült”-et ír úgy, hogy valójában nem hívta meg a dokumentumkészítő eszközt."""
    kept = [l for l in str(content).splitlines() if not l.startswith((CREATED_MARK, PROBLEM_MARK))]
    return "\n".join(kept).strip() or "(A fájl elkészült.)"

def find_doc(docs, name, not_after=None):
    """A megadott nevű dokumentum; azonos nevűek közül az, amelyik az üzenet előtt utoljára készült."""
    same = [d for d in docs if d["name"] == name]  # a lista a legújabbal kezdődik
    if same and not_after:
        try:
            limit = datetime.fromisoformat(str(not_after))
            for d in same:
                if datetime.fromisoformat(str(d["created_at"])) <= limit:
                    return d
        except Exception:
            pass
    return same[0] if same else None

def unique_name(name, taken):
    """Ha már van ilyen nevű fájl a projektben, sorszámot kap (így az új változat nem keveredik a régivel)."""
    if name not in taken:
        return name
    stem, _, ext = name.rpartition(".")
    n = 2
    while f"{stem}_{n}.{ext}" in taken:
        n += 1
    return f"{stem}_{n}.{ext}"

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
        st.write("Az itt tárolt dokumentumok (TXT, PDF), képek (PNG, JPG) és a Piri által készített fájlok (szöveges dokumentum, Excel, PowerPoint) kizárólag ehhez a projekthez tartoznak, más projektben nem jelennek meg.")

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
            mime = doc["mime_type"]
            is_image = mime.startswith("image/")
            is_md = is_markdown_doc(doc)
            icon = ("🖼️" if is_image else "📝" if is_md else "📊" if mime == ex.XLSX_MIME
                    else "📽️" if mime == ex.PPTX_MIME else "📄")
            col_info, col_dl, col_prev, col_del = st.columns([5, 1.7, 1.7, 0.8])
            size_kb = max(1, round((doc.get("size_bytes") or 0) / 1024))
            col_info.write(f"{icon} **{doc['name']}** · {size_kb} KB · {str(doc.get('created_at', ''))[:10]}")
            want_download = col_dl.checkbox("Letöltés", key=f"dl_{doc['id']}")
            want_preview = (is_image or is_md) and col_prev.checkbox("Előnézet", key=f"prev_{doc['id']}")
            if col_del.button("🗑️", key=f"del_{doc['id']}", help="Dokumentum törlése a projektből"):
                if delete_document(doc["id"]):
                    st.rerun()
                else:
                    st.error("A törlés nem sikerült.")
            if want_download:
                render_downloads(doc)
            if want_preview:
                try:
                    raw = base64.b64decode(get_document_content(doc["id"]))
                    if is_image:
                        st.image(raw, caption=doc["name"], width=400)
                    else:
                        with st.container(border=True):
                            st.markdown(raw.decode("utf-8", errors="replace"))
                except Exception:
                    st.warning("Az előnézet nem tölthető be.")
    
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
            for i, msg in enumerate(messages):
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])
                    if msg["role"] != "assistant":
                        continue
                    # A válaszban készült fájlok letöltése közvetlenül a chatből: a legutóbbi válasznál azonnal
                    # látszanak a gombok, a régebbieknél pipára töltődnek be (hogy ne lassítsák az oldalt).
                    msg_key = msg.get("id", i)
                    for name in created_names(msg["content"]):
                        doc = find_doc(project_docs, name, msg.get("created_at"))
                        if not doc:
                            st.caption(f"`{name}` nem található a dokumentumtárban.")
                        elif i == len(messages) - 1 or st.checkbox(f"⬇️ {name} letöltése",
                                                                   key=f"chat_dl_{msg_key}_{doc['id']}"):
                            render_downloads(doc, key_prefix=f"chat_{msg_key}_")

            # Ha Piri a dokumentumot a chatbe írta (fájl nélkül), egy kattintással letölthető fájl lesz belőle
            last = messages[-1]
            if last["role"] == "assistant" and not created_names(last["content"]):
                saved_answers = st.session_state.setdefault("saved_answers", {})
                answer_key = f"{current_project_id}:{last.get('id', len(messages))}"
                if answer_key in saved_answers:
                    saved_doc = find_doc(project_docs, saved_answers[answer_key])
                    if saved_doc:
                        render_downloads(saved_doc, key_prefix="saved_")
                elif st.button("💾 A legutóbbi válasz mentése dokumentumként", key=f"save_answer_{answer_key}",
                               help="Piri válasza a dokumentumtárba kerül, és Word, PDF vagy Markdown formátumban letölthető."):
                    body = strip_app_notes(last["content"])
                    heading = re.search(r"^#{1,3}\s+(.+)$", body, flags=re.MULTILINE)
                    title = heading.group(1).strip("* ") if heading else f"Piri válasza {date.today().isoformat()}"
                    file_name = unique_name(ex.safe_filename(title, "md"), {d["name"] for d in project_docs})
                    ok, detail = save_document_bytes(current_project_id, file_name, ex.MD_MIME,
                                                     (body + "\n").encode("utf-8"))
                    if ok:
                        saved_answers[answer_key] = file_name
                        st.rerun()
                    else:
                        st.error(f"A mentés nem sikerült: {detail}")

        if user_input := st.chat_input("Kérdezz Piritól, vagy kérj elemzést a csatolt fájlra..."):
            with st.chat_message("user"):
                st.write(user_input)
            
            save_message(current_project_id, "user", user_input)
            
            api_messages = []
            if messages and isinstance(messages, list):
                api_messages = [
                    {"role": m["role"],
                     "content": strip_app_notes(m["content"]) if m["role"] == "assistant" else m["content"]}
                    for m in messages if "role" in m
                ]
            
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

                # Excel / PowerPoint / Word: szöveggé alakítva (a képletek is látszanak)
                elif mime in (ex.XLSX_MIME, ex.PPTX_MIME, ex.DOCX_MIME):
                    try:
                        office_text = ex.office_to_text(mime, base64.b64decode(b64_data))
                    except Exception:
                        office_text = None
                    if office_text:
                        text_attachments.append(f"[Mellékelt fájl tartalma ({doc['name']}):\n{office_text}]")

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
                "A válaszban jelöld meg, mely forrásokra támaszkodtál.\n\n"
                "DOKUMENTUMKÉSZÍTÉS:\n"
                "Ha a felhasználó dokumentum, táblázat vagy prezentáció készítését kéri, használd a megfelelő eszközt: "
                "create_document (szöveges dokumentum, amelyet a felhasználó Word, PDF vagy Markdown formátumban tölt le), "
                "create_spreadsheet (Excel táblázat, amelyben a számolt értékek képletek, a számok pedig megfelelő "
                "számformátumúak legyenek, hogy a felhasználó tovább tudjon dolgozni vele), "
                "create_presentation (PowerPoint). Egyszerű kérdésre ne készíts fájlt, arra a chatben válaszolj. "
                "Fájl kizárólag az eszköz tényleges meghívásával jön létre: a kért dokumentum teljes szövegét ne a "
                "chatbe írd, hanem az eszköznek add át, és soha ne állítsd, hogy egy fájl elkészült, ha az eszköz "
                "ezt nem igazolta vissza. Nagyon hosszú anyagot bonts több fájlra, válaszonként egy eszközhívással. "
                "A fájl elkészítése után röviden írd le, mit tartalmaz és mire kell figyelni; a letöltőgombokat az "
                "alkalmazás teszi a válaszod alá, te ne írj letöltési hivatkozást vagy „Elkészült” sort. "
                "A korábban elkészült fájlok tartalmát a mellékelt dokumentumok között látod; "
                "módosítást új fájl készítésével végezz, és jelezd, hogy új változat készült. "
                "Ha egy állítás bizonytalan vagy ellenőrzést igényel, a dokumentumban is jelöld."
            )

            # Eszközök: a beépített webes kereső (az Anthropic szerverein fut) és a dokumentumkészítők (nálunk futnak)
            tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}] + ex.TOOLS

            taken_names = {d["name"] for d in project_docs}

            def save_created_file(name, mime, data):
                """Piri által készített fájl mentése; siker esetén a tárolt (egyedi) fájlnevet adja vissza."""
                final_name = unique_name(name, taken_names)
                ok, detail = save_document_bytes(current_project_id, final_name, mime, data)
                if ok:
                    taken_names.add(final_name)
                return ok, (final_name if ok else detail)

            with st.chat_message("assistant"):
                with st.spinner("Piri elemzi a tartalmat, keres és gondolkodik... (hosszabb dokumentumnál ez több perc is lehet)"):
                    answer, sources, created_files, problems = chat_flow.run_conversation(
                        claude_client,
                        "claude-haiku-5-5",  # A Claude Haiku 3.5 2026.02.19-én kivezetésre került
                        system_instruction,
                        api_messages,
                        tools,
                        save_created_file,
                    )
                    answer = answer or "(Piri most nem adott szöveges választ.)"
                    # A hibát az elmentett válaszba is beírjuk, mert az oldal rögtön újratöltődik
                    if problems:
                        answer += f"\n\n{PROBLEM_MARK} " + " ".join(problems)
                    if created_files:
                        answer += (f"\n\n{CREATED_MARK} " + ", ".join(f"`{n}`" for n in created_files)
                                   + " – itt lent és a **Dokumentumok** fülön is letölthető.")
                    if sources:
                        answer += "\n\n**Források:**\n" + "\n".join(f"- [{title}]({url})" for url, title in sources.items())
                    st.write(answer)
            
            save_message(current_project_id, "assistant", answer)
            st.rerun()
            
    with tab_diagrams:
        st.subheader("Generált folyamatábrák")
else:
    st.write("### 👈 Kezdéshez válassz vagy hozz létre egy projektet a bal oldali sávban!")

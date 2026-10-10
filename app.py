import base64
import html
import inspect
import os
import re
from datetime import date, datetime

import streamlit as st
from anthropic import Anthropic

import chat_flow
import db
import export_tools as ex
import search_tools as stx

# Frissítés után a futó alkalmazás néha a saját moduljaink régi, memóriában maradt változatát használja
# (ilyenkor pl. „db.get_tasks” hiányzik). Ha ezt észleljük, újratöltjük őket, így nem kell kézzel újraindítani.
if (not hasattr(db, "get_tasks") or not hasattr(db, "delete_summary")
        or "handlers" not in inspect.signature(chat_flow.run_conversation).parameters):
    import importlib
    for _module in (stx, ex, db, chat_flow):
        importlib.reload(_module)

# Kényszerített oldal konfiguráció a legelső sorban
st.set_page_config(page_title="Piri Asszisztens", layout="wide")

# --- BEÁLLÍTÁSOK -----------------------------------------------------------
MODEL = "claude-haiku-5-5"  # A Claude Haiku 3.5 2026.02.19-én kivezetésre került

# A beszélgetés és a többi fül görgethető dobozának magassága. A doboz a böngészőablak magasságához
# igazodik: ablakmagasság mínusz az alábbi képpontérték (fejléc, fülek, beviteli mező helye).
# Ha a doboz alatt üres sáv marad, csökkentsd a számot; ha az oldal görgethetővé válik, növeld.
CHAT_OFFSET_PX = 310    # Beszélgetés fül
PANEL_OFFSET_PX = 205   # Dokumentumok és Összefoglalók fül
SEARCH_OFFSET_PX = 155  # keresési találatok (itt nincsenek fülek)
FALLBACK_HEIGHT_PX = 520  # régebbi Streamlit esetén ez a fix magasság érvényes

MAX_FILE_MB = 10   # a tartalom Base64-ként az adatbázisban tárolódik, ezért korlátozzuk a méretet
MAX_IMAGE_MB = 5   # ennél nagyobb képet a modell nem fogad el
DOC_TYPES = ["txt", "pdf", "png", "jpg", "jpeg", "docx", "xlsx", "pptx"]  # a dokumentumtárba feltölthető
ATTACH_TYPES = ["png", "jpg", "jpeg", "gif", "webp", "pdf", "txt", "md", "csv", "docx", "xlsx", "pptx"]
EXT_MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
    "pdf": ex.PDF_MIME, "txt": "text/plain", "md": ex.MD_MIME, "csv": "text/csv",
    "docx": ex.DOCX_MIME, "xlsx": ex.XLSX_MIME, "pptx": ex.PPTX_MIME,
}

# A gombok teljes szélességét az újabb Streamlit width="stretch"-ként, a régebbi use_container_width-ként kéri
STRETCH = ({"width": "stretch"} if "width" in inspect.signature(st.button).parameters
           else {"use_container_width": True})

# --- KULCSOK BIZTONSÁGOS BETÖLTÉSE ---
try:
    SUPABASE_URL = str(st.secrets["SUPABASE_URL"]).strip().strip("'").strip('"')
    SUPABASE_KEY = str(st.secrets["SUPABASE_KEY"]).strip().strip("'").strip('"')
    ANTHROPIC_API_KEY = str(st.secrets["ANTHROPIC_API_KEY"]).strip().strip("'").strip('"')
except Exception:
    st.error("Hiba! Hiányzik a Secrets konfiguráció a Streamlit felületén.")
    st.stop()

claude_client = Anthropic(api_key=ANTHROPIC_API_KEY.replace("'", "").replace('"', ""))
db.init(SUPABASE_URL, SUPABASE_KEY)

# --- MEGJELENÉS ------------------------------------------------------------
CSS = f"""
<style>
/* kevesebb üres hely az oldal tetején és alján, hogy a beszélgetés kitöltse a képernyőt */
.block-container, [data-testid="stMainBlockContainer"] {{ padding-top: 3.75rem !important; padding-bottom: 1rem !important; }}

/* TÖMÖREBB FELÜLET (az alap betűméretet a .streamlit/config.toml állítja: theme.baseFontSize) */
/* kisebb térköz az egymás alatti elemek között, alacsonyabb gombok, vékonyabb elválasztók */
[data-testid="stVerticalBlock"] {{ gap: .6rem; }}
.stButton button, .stDownloadButton button, .stFormSubmitButton button, [data-testid="stPopover"] button {{
    min-height: 2rem !important; padding: .15rem .75rem !important; }}
hr {{ margin: .5rem 0 !important; }}
[data-testid="stExpander"] summary {{ padding-top: .35rem !important; padding-bottom: .35rem !important; min-height: 0 !important; }}
/* oldalsáv: kevesebb üres hely felül, kisebb címek */
[data-testid="stSidebarHeader"] {{ height: auto !important; min-height: 2rem; padding-top: .5rem !important; padding-bottom: 0 !important; }}
[data-testid="stSidebarUserContent"] {{ padding-top: .5rem !important; }}
[data-testid="stSidebar"] h2 {{ font-size: 1.15rem !important; padding: .2rem 0 .3rem !important; margin: 0 !important; line-height: 1.4 !important; }}
[data-testid="stSidebar"] h3 {{ font-size: 1rem !important; padding: .2rem 0 .3rem !important; margin: 0 !important; line-height: 1.4 !important; }}
[data-testid="stSidebar"] [data-testid="stHeading"] {{ margin: 0 !important; overflow: visible !important; }}
/* az összefoglalók apró szerkesztés- és törlésgombja */
[class*="st-key-sum_editbtn_"] button, [class*="st-key-sum_delbtn_"] button,
[class*="st-key-task_editbtn_"] button, [class*="st-key-task_delbtn_"] button {{
    min-height: 1.7rem !important; padding: 0 .45rem !important; }}

/* keskeny, mindig látható fejlécsor */
.piri-header {{ font-size: 1.15rem; font-weight: 600; line-height: 2.5rem; white-space: nowrap;
               overflow: hidden; text-overflow: ellipsis; }}
.piri-header .sep {{ margin: 0 .6rem; opacity: .35; font-weight: 400; }}
.piri-header .badge {{ margin-left: .5rem; font-size: .85rem; font-weight: 400; opacity: .7; }}

/* kisebb címsorok Piri válaszaiban és az előnézetekben (a törzsszöveg változatlan) */
[data-testid="stMarkdownContainer"] h1 {{ font-size: 1.3rem !important; font-weight: 700 !important; padding: .55rem 0 .2rem !important; }}
[data-testid="stMarkdownContainer"] h2 {{ font-size: 1.2rem !important; font-weight: 700 !important; padding: .5rem 0 .2rem !important; }}
[data-testid="stMarkdownContainer"] h3 {{ font-size: 1.1rem !important; font-weight: 700 !important; padding: .45rem 0 .15rem !important; }}
[data-testid="stMarkdownContainer"] h4,
[data-testid="stMarkdownContainer"] h5,
[data-testid="stMarkdownContainer"] h6 {{ font-size: 1rem !important; font-weight: 700 !important; padding: .4rem 0 .1rem !important; }}

/* a görgethető dobozok a böngészőablak magasságához igazodnak */
/* (A :has() szabályok külön állnak: amelyik böngésző nem ismeri, az csak azt a blokkot hagyja ki.
   A dvh a táblagépek és telefonok ténylegesen látható ablakmagassága; ahol nincs, a vh érvényes.) */
.st-key-chat_box {{ height: calc(100vh - {CHAT_OFFSET_PX}px) !important; height: calc(100dvh - {CHAT_OFFSET_PX}px) !important; min-height: 260px; }}
.st-key-docs_box, .st-key-sums_box, .st-key-tasks_box {{ height: calc(100vh - {PANEL_OFFSET_PX}px) !important; height: calc(100dvh - {PANEL_OFFSET_PX}px) !important; min-height: 260px; }}
.st-key-search_box {{ height: calc(100vh - {SEARCH_OFFSET_PX}px) !important; height: calc(100dvh - {SEARCH_OFFSET_PX}px) !important; min-height: 260px; }}
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > .st-key-chat_box) {{
    height: calc(100vh - {CHAT_OFFSET_PX}px) !important; height: calc(100dvh - {CHAT_OFFSET_PX}px) !important; min-height: 260px; }}
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > .st-key-docs_box),
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > .st-key-sums_box),
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > .st-key-tasks_box) {{
    height: calc(100vh - {PANEL_OFFSET_PX}px) !important; height: calc(100dvh - {PANEL_OFFSET_PX}px) !important; min-height: 260px; }}
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > .st-key-search_box) {{
    height: calc(100vh - {SEARCH_OFFSET_PX}px) !important; height: calc(100dvh - {SEARCH_OFFSET_PX}px) !important; min-height: 260px; }}

/* A fix magasságú dobozban a tartalom görgessen, ne zsugorodjon: enélkül a megadott magasságú elemek
   (pl. a szerkesztőmezők) összenyomódnak, amikor a tartalom nem fér ki. */
.st-key-chat_box > *, .st-key-docs_box > *, .st-key-sums_box > *, .st-key-search_box > *, .st-key-tasks_box > *,
.st-key-tasks_box [data-testid="stElementContainer"],
.st-key-chat_box [data-testid="stElementContainer"], .st-key-docs_box [data-testid="stElementContainer"],
.st-key-sums_box [data-testid="stElementContainer"], .st-key-search_box [data-testid="stElementContainer"] {{
    flex-shrink: 0 !important; }}

/* keresési találatok */
.piri-hit {{ margin: .1rem 0 .2rem 0; }}
.piri-hit .title {{ font-weight: 600; }}
.piri-hit .meta {{ opacity: .6; font-size: .85rem; margin-left: .4rem; }}
.piri-hit .snip {{ font-size: .92rem; opacity: .9; margin-top: .15rem; }}
.piri-hit mark, .piri-header mark {{ background: #ffe58a; color: inherit; padding: 0 .12em; border-radius: 3px; }}
</style>
"""


def inject_css():
    # st.html a csak stílust tartalmazó blokkot hely foglalása nélkül illeszti be
    if hasattr(st, "html"):
        st.html(CSS)
    else:
        st.markdown(CSS, unsafe_allow_html=True)


# --- GYORSÍTÓTÁRAZOTT BETÖLTÉSEK (a tárolt fájlok nem módosulnak) ---
@st.cache_data(show_spinner=False, max_entries=40)
def get_document_content(doc_id):
    return db.get_document_content(doc_id)


@st.cache_data(show_spinner=False, max_entries=60)
def get_attachment_content(attachment_id):
    return db.get_attachment_content(attachment_id)


@st.cache_data(show_spinner=False, max_entries=20)
def export_markdown(doc_id, fmt, title):
    """A Piri által készített Markdown dokumentum átalakítása Word vagy PDF formátumra."""
    text = base64.b64decode(get_document_content(doc_id)).decode("utf-8", errors="replace")
    return ex.markdown_to_docx(text, title) if fmt == "docx" else ex.markdown_to_pdf(text, title)


# --- ÁLTALÁNOS SEGÉDFÜGGVÉNYEK ----------------------------------------------
def parse_ts(value):
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def fmt_dt(value):
    """Adatbázis-időbélyeg magyar idő szerint, pl. 2026.10.10 18:40."""
    ts = parse_ts(value)
    if ts is None:
        return str(value or "")[:16].replace("T", " ")
    try:
        from zoneinfo import ZoneInfo
        ts = ts.astimezone(ZoneInfo("Europe/Budapest"))
    except Exception:
        pass
    return ts.strftime("%Y.%m.%d %H:%M")


def guess_mime(name, given=""):
    ext = str(name).rsplit(".", 1)[-1].lower() if "." in str(name) else ""
    return EXT_MIME.get(ext) or given or "application/octet-stream"


def is_markdown_doc(doc):
    return doc["mime_type"] == ex.MD_MIME or doc["name"].lower().endswith(".md")


def doc_icon(doc):
    mime = doc["mime_type"]
    return ("🖼️" if mime.startswith("image/") else "📝" if is_markdown_doc(doc) else "📊" if mime == ex.XLSX_MIME
            else "📽️" if mime == ex.PPTX_MIME else "📄")


def save_document_bytes(project_id, name, mime_type, data):
    """Mentés a dokumentumtárba a kereséshez kinyert szöveggel együtt. Visszaad: (sikerült, hiba oka)."""
    try:
        db.save_document(project_id, name, mime_type, data, ex.extract_text(name, mime_type, data))
        return True, ""
    except db.DbError as e:
        return False, str(e)


def render_downloads(doc, key_prefix=""):
    """Letöltőgombok egy dokumentumhoz (a tartalom csak itt, igény szerint töltődik be).
    A key_prefix azért kell, mert ugyanaz a dokumentum több helyen is megjelenhet."""
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


def render_doc_preview(doc, text=None):
    """Dokumentum előnézete: kép, Markdown, vagy a kinyert szöveg eleje."""
    try:
        if doc["mime_type"].startswith("image/"):
            st.image(base64.b64decode(get_document_content(doc["id"])), caption=doc["name"], width=400)
        elif is_markdown_doc(doc):
            st.markdown(base64.b64decode(get_document_content(doc["id"])).decode("utf-8", errors="replace"))
        else:
            text = db.get_document_text(doc["id"]) if text is None else text
            if text.strip():
                st.text(text[:6000] + ("\n[…]" if len(text) > 6000 else ""))
            else:
                st.caption("Ehhez a fájlhoz nincs szöveges előnézet; letöltve megnyitható.")
    except Exception:
        st.warning("Az előnézet nem tölthető be.")


# --- A CHATBEN KÉSZÜLT FÁJLOK NYOMON KÖVETÉSE ---
# Ezeket a sorokat az alkalmazás fűzi Piri válasza alá (nem Piri írja).
CREATED_MARK = "📎 **Elkészült:**"
PROBLEM_MARK = "⚠️ **Figyelem:**"
TASK_MARK = "🗒️ **Feladatok:**"


def created_names(content):
    """Az üzenet alá fűzött „Elkészült” sorból a fájlnevek."""
    for line in str(content).splitlines():
        if line.startswith(CREATED_MARK):
            return list(dict.fromkeys(re.findall(r"`([^`]+)`", line)))
    return []


def strip_app_notes(content):
    """Az alkalmazás által hozzáfűzött sorok nélkül adjuk vissza a választ Pirinek, különben utánozni kezdi
    őket: „Elkészült”-et ír úgy, hogy valójában nem hívta meg a dokumentumkészítő eszközt."""
    kept = [l for l in str(content).splitlines() if not l.startswith((CREATED_MARK, PROBLEM_MARK, TASK_MARK))]
    return "\n".join(kept).strip() or "(A fájl elkészült.)"


def find_doc(docs, name, not_after=None):
    """A megadott nevű dokumentum; azonos nevűek közül az, amelyik az üzenet előtt utoljára készült."""
    same = [d for d in docs if d["name"] == name]  # a lista a legújabbal kezdődik
    limit = parse_ts(not_after) if not_after else None
    if same and limit:
        for d in same:
            created = parse_ts(d.get("created_at"))
            if created and created <= limit:
                return d
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


# --- A MODELLNEK ÁTADOTT TARTALOM ÖSSZEÁLLÍTÁSA -------------------------------
def file_parts(name, mime, b64_data):
    """Egy fájl a modell számára. Visszaad: (tartalomblokkok, szöveges mellékletek)."""
    if mime.startswith("image/"):
        return [{"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64_data}}], []
    if mime == ex.PDF_MIME:
        return [{"type": "document", "title": name,
                 "source": {"type": "base64", "media_type": ex.PDF_MIME, "data": b64_data}}], []
    text = None
    if mime.startswith("text/"):
        text = base64.b64decode(b64_data).decode("utf-8", errors="replace")
    elif mime in (ex.XLSX_MIME, ex.PPTX_MIME, ex.DOCX_MIME):  # szöveggé alakítva (a képletek is látszanak)
        try:
            text = ex.office_to_text(mime, base64.b64decode(b64_data))
        except Exception:
            text = None
    return [], ([f"[Mellékelt fájl tartalma ({name}):\n{text}]"] if text else [])


def user_content(text, files):
    """Felhasználói üzenet tartalma: files = [(név, mime, base64)], a szöveg a végére kerül."""
    blocks, texts = [], []
    for name, mime, b64_data in files:
        b, t = file_parts(name, mime, b64_data)
        blocks += b
        texts += t
    full_text = "\n\n".join(texts + [text])
    return blocks + [{"type": "text", "text": full_text}] if blocks else full_text


def load_attachment_files(attachments):
    files = []
    for att in attachments:
        try:
            files.append((att["name"], att["mime_type"], get_attachment_content(att["id"])))
        except Exception:
            pass  # a hiányzó munkaanyag ne akassza meg a beszélgetést
    return files


def build_history(messages, atts_by_msg):
    """A tárolt beszélgetés a modell számára, az üzenetekhez csatolt munkaanyagokkal együtt."""
    history = []
    for m in messages:
        if m.get("role") == "assistant":
            history.append({"role": "assistant", "content": strip_app_notes(m["content"])})
        elif m.get("role") == "user":
            files = load_attachment_files(atts_by_msg.get(m.get("id"), []))
            history.append({"role": "user", "content": user_content(m["content"], files)})
    return history


def summaries_for_prompt(summaries):
    if not summaries:
        return ""
    parts = [f"### Összefoglaló – {fmt_dt(s['created_at'])}\n{s['content']}" for s in summaries]
    return (
        "\n\nKORÁBBI ÖSSZEFOGLALÓK:\n"
        "A projekt korábbi beszélgetéseit a felhasználó összefoglaltatta veled, majd törölte; az alábbi "
        "összefoglalók tartalmazzák, ami azokból megmaradt (időrendben). Tekintsd ezeket a saját korábbi "
        "ismereteidnek, építs rájuk, és ha a felhasználó kéri, mutasd meg őket.\n\n" + "\n\n".join(parts)
    )


# --- FELADATOK: ÁLLAPOTOK, PIRI ESZKÖZEI ---------------------------------------
# A pipa azt jelenti, hogy a magunk részét elvégeztük; pipa nélkül a feladat nyitott (nálunk a labda).
TASK_STATUS_LABELS = {"open": "nyitott", "waiting": "választ várunk", "done": "kész",
                      "obsolete": "elavult", "cancelled": "törölt"}
TASK_ACTIVE = ("open", "waiting")           # ezek látszanak alapból
TASK_CHECKED = ("waiting", "done", "obsolete", "cancelled")  # pipált feladat lehetséges állapotai
NO_TOPIC = "Egyéb"

TASK_TOOLS = [
    {
        "name": "add_task",
        "description": "Új tennivaló felvétele a projekt Feladatok listájára. Csak akkor hívd meg, ha a "
                       "felhasználó kifejezetten kéri a felvételt.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "A téma rövid neve (pl. Vízhálózat). Ha van már "
                                                           "illő téma a listán, pontosan azt használd."},
                "title": {"type": "string", "description": "A tennivaló egy mondatban (pl. Gépésznek megírni a specifikációt)."},
                "note": {"type": "string", "description": "Rövid megjegyzés, ha van (nem kötelező)."},
            },
            "required": ["topic", "title"],
        },
    },
    {
        "name": "update_task",
        "description": "Meglévő feladat állapotának, megjegyzésének, szövegének vagy témájának módosítása. "
                       "Csak akkor hívd meg, ha a felhasználó kifejezetten kéri.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "A feladat azonosítója a listából (a # utáni szám)."},
                "status": {"type": "string", "enum": list(TASK_STATUS_LABELS),
                           "description": "open = nyitott (nálunk a labda), waiting = választ várunk, done = kész, "
                                          "obsolete = elavult, cancelled = törölt (nem kell elvégezni)."},
                "note": {"type": "string"},
                "title": {"type": "string"},
                "topic": {"type": "string"},
            },
            "required": ["task_id"],
        },
    },
]


def task_status(task):
    return task.get("status") if task.get("status") in TASK_STATUS_LABELS else "open"


def task_topic(task):
    return (task.get("topic") or "").strip() or NO_TOPIC


def task_line(task):
    note = f" (megjegyzés: {task['note']})" if task.get("note") else ""
    return f"#{task['id']} [{TASK_STATUS_LABELS[task_status(task)]}] {task_topic(task)} » {task['title']}{note}"


def match_topic(topic, tasks):
    """Ha már van ilyen téma (kis- és nagybetűtől függetlenül), annak az írásmódját használjuk."""
    topic = str(topic or "").strip()
    for t in tasks:
        if task_topic(t).lower() == topic.lower():
            return task_topic(t)
    return topic or NO_TOPIC


def tasks_for_prompt(tasks):
    if tasks is None:  # a feladatok táblája még nincs létrehozva: Piri nem kap róla sem leírást, sem eszközt
        return ""
    listing = "\n".join(task_line(t) for t in tasks[-200:]) or "(még nincs feladat)"
    return (
        "\n\nFELADATOK:\n"
        "A projekthez feladatlista tartozik (Feladatok fül), két szinten: téma » tennivaló. Állapotok: nyitott "
        "(nálunk a labda), választ várunk, kész, elavult, törölt (nem kell elvégezni; az okot a megjegyzés őrzi). "
        "Feladatot felvenni (add_task) vagy módosítani (update_task) csak akkor szabad, ha a felhasználó "
        "kifejezetten kéri. Ha a beszélgetésben teendő merül fel, magadtól ne vedd fel, csak ajánld fel egy "
        "mondatban, a téma és a tennivaló megnevezésével. Soha ne állítsd, hogy egy feladatot felvettél vagy "
        "módosítottál, ha az eszköz ezt nem igazolta vissza. Feladatot törölni nem tudsz; azt a felhasználó "
        "teheti meg a Feladatok fülön. A jelenlegi lista:\n" + listing
    )


def make_task_handlers(project_id, tasks, events):
    """Piri feladatkezelő eszközeinek végrehajtói. Az events listába kerül, ami ténylegesen megtörtént."""
    by_id = {t["id"]: t for t in tasks}

    def add(inp):
        title = str(inp.get("title") or "").strip()
        if not title:
            raise ValueError("A tennivaló szövege hiányzik.")
        topic = match_topic(inp.get("topic"), list(by_id.values()))
        row = db.add_task(project_id, topic, title, str(inp.get("note") or ""))
        by_id[row["id"]] = row
        events.append(f"felvéve: {topic} » {title}")
        return f"Felvéve a Feladatok listájára: {task_line(row)}"

    def update(inp):
        try:
            task_id = int(inp.get("task_id"))
        except (TypeError, ValueError):
            raise ValueError("Hiányzik a feladat azonosítója (task_id).")
        if task_id not in by_id:
            raise ValueError("Ebben a projektben nincs ilyen azonosítójú feladat.")
        fields = {}
        if inp.get("status") is not None:
            if inp["status"] not in TASK_STATUS_LABELS:
                raise ValueError("Ismeretlen állapot.")
            fields["status"] = inp["status"]
        if isinstance(inp.get("note"), str):
            fields["note"] = inp["note"].strip()
        if isinstance(inp.get("title"), str) and inp["title"].strip():
            fields["title"] = inp["title"].strip()
        if isinstance(inp.get("topic"), str) and inp["topic"].strip():
            fields["topic"] = match_topic(inp["topic"], list(by_id.values()))
        if not fields:
            raise ValueError("Nincs megadva, mit kell módosítani.")
        row = db.update_task(task_id, **fields)
        by_id[task_id] = row
        events.append(f"módosítva: {task_topic(row)} » {row['title']} ({TASK_STATUS_LABELS[task_status(row)]})")
        return f"Módosítva: {task_line(row)}"

    return {"add_task": add, "update_task": update}


def build_system(summaries, tasks=None):
    # SYSTEM PROMPT A GYÖNYÖRŰ MAGYAR JOGI NYELVÉRT
    return (
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
        "Ha egy állítás bizonytalan vagy ellenőrzést igényel, a dokumentumban is jelöld.\n\n"
        "MUNKAANYAGOK:\n"
        "A felhasználó a kérdéseihez képet vagy fájlt csatolhat. Ezek munkaanyagok: a beszélgetés részei, de "
        "nem kerülnek a projekt dokumentumtárába, és az előzmények törlésekor törlődnek."
        + tasks_for_prompt(tasks)
        + summaries_for_prompt(summaries)
    )


def summary_system(summaries):
    return (
        "Te Pirita (Piri) vagy, professzionális magyar jogi és adózási AI asszisztens. Most nem kérdésre "
        "válaszolsz, hanem a saját, felhasználóval folytatott beszélgetésedről írsz pontos, tömör, de "
        "hiánytalan összefoglalót, kifogástalan magyar nyelven." + summaries_for_prompt(summaries)
    )


# --- PROJEKTMŰVELETEK --------------------------------------------------------
def open_project(project_id):
    """Projekt megnyitása; a megnyitás idejét eltároljuk, hogy legközelebb ez induljon."""
    st.session_state["current_project_id"] = project_id
    st.session_state["view"] = "project"
    try:
        db.update_project(project_id, last_opened_at=db.now_iso())
    except db.DbError:
        pass  # ha nem sikerül eltárolni, a projekt attól még megnyílik


def top_sort_order(projects):
    orders = [p["sort_order"] for p in projects if p.get("sort_order") is not None]
    return (min(orders) if orders else 0) - 1


def move_project(active, project_id, delta):
    """A projekt eggyel feljebb (-1) vagy lejjebb (+1) kerül; a sorrendet sorszámként tároljuk."""
    ids = [p["id"] for p in active]
    i = ids.index(project_id)
    j = i + delta
    if not 0 <= j < len(ids):
        return
    ids[i], ids[j] = ids[j], ids[i]
    current = {p["id"]: p.get("sort_order") for p in active}
    for n, pid in enumerate(ids):
        if current[pid] != n:
            db.update_project(pid, sort_order=n)


def dialog(title, on_dismiss, **kwargs):
    """st.dialog; az ablak X-szel bezárásakor az on_dismiss törli a „nyitva van” jelzést (ahol a Streamlit tudja)."""
    if "on_dismiss" in inspect.signature(st.dialog).parameters:
        kwargs["on_dismiss"] = on_dismiss
    return st.dialog(title, **kwargs)


def _close_delete_dialog():
    st.session_state.pop("delete_open", None)


@dialog("Projekt végleges törlése", _close_delete_dialog)
def delete_dialog(project):
    st.write(f"Biztosan törlöd a(z) **{project['name']}** projektet?")
    st.warning("A törlés végleges, és mindent visz: a beszélgetést, a csatolt munkaanyagokat, "
               "a dokumentumtár összes fájlját és az összefoglalókat.")
    c1, c2 = st.columns(2)
    if c1.button("🗑️ Igen, végleges törlés", type="primary", key="delete_yes", **STRETCH):
        try:
            db.delete_project(project["id"])
        except db.DbError as e:
            st.error(f"A törlés nem sikerült: {e}")
            return
        _close_delete_dialog()
        st.session_state.pop("current_project_id", None)
        st.rerun()
    if c2.button("Mégse", key="delete_no", **STRETCH):
        _close_delete_dialog()
        st.rerun()


# --- ÖSSZEFOGLALÁS ÉS ELŐZMÉNYEK TÖRLÉSE --------------------------------------
def _close_compact_dialog():
    st.session_state.pop("compact_open", None)


@dialog("🧹 Összefoglalás és előzmények törlése", _close_compact_dialog, width="large")
def compact_dialog(project, messages, atts_by_msg, summaries, project_docs):
    pid = project["id"]
    message_ids = [m["id"] for m in messages if m.get("id") is not None]
    signature = (pid, len(messages), messages[-1].get("id"))
    draft = st.session_state.get("compact_draft")
    n_atts = sum(len(v) for v in atts_by_msg.values())

    def generate(fix_request="", previous=""):
        return chat_flow.summarize(
            claude_client, MODEL, summary_system(summaries), build_history(messages, atts_by_msg),
            doc_names=[d["name"] for d in project_docs], fix_request=fix_request, previous_draft=previous)

    if not draft or draft["signature"] != signature:
        with st.spinner("Piri összefoglalja a beszélgetést…"):
            try:
                description, content = generate()
            except Exception as e:
                st.error(f"Az összefoglaló nem készült el: {e}")
                st.caption("Semmi nem törlődött. Zárd be az ablakot, és próbáld meg újra.")
                return
        draft = {"signature": signature, "description": description, "content": content, "nonce": 0}
        st.session_state["compact_draft"] = draft

    st.caption(
        f"Ez Piri tervezete. Nézd át, és ha kell, írd át. Jóváhagyás után a projekt {len(messages)} üzenete"
        + (f" és {n_atts} csatolt munkaanyaga" if n_atts else "")
        + " véglegesen törlődik az adatbázisból, és Piri ezután az összefoglalókból dolgozik. "
          "A dokumentumtár nem változik.")
    nonce = draft["nonce"]
    description = st.text_area("Rövid leírás (2–3 mondat, ez látszik a listában)", value=draft["description"],
                               height=90, key=f"cd_desc_{nonce}")
    content = st.text_area("Összefoglaló (Markdown)", value=draft["content"], height=360, key=f"cd_content_{nonce}")
    with st.expander("Előnézet formázva"):
        st.markdown(content)
    fix_request = st.text_input("Mit javítson rajta Piri? (csak az újraíráshoz kell)", key=f"cd_fix_{nonce}",
                                placeholder="pl. írd bele a három leányvállalat pontos számait is")

    c1, c2, c3 = st.columns([2.2, 1.6, 1])
    if c1.button("✅ Jóváhagyás és előzmények törlése", type="primary", key="cd_approve", **STRETCH):
        if not content.strip():
            st.error("Az összefoglaló üres, így nem menthető.")
            return
        try:
            db.add_summary(pid, description.strip(), content.strip())
        except db.DbError as e:
            st.error(f"Az összefoglaló mentése nem sikerült, ezért semmi nem törlődött: {e}")
            return
        try:
            db.delete_messages(pid, message_ids)
        except db.DbError as e:
            st.session_state["chat_flash"] = ("error", "Az összefoglaló elmentve, de az előzmények törlése "
                                                       f"nem sikerült: {e}")
        else:
            st.session_state["chat_flash"] = ("success", "Az összefoglaló elkészült, az előzmények törölve. "
                                                         "Az Összefoglalók fülön megnézheted és szerkesztheted.")
        st.session_state.pop("compact_draft", None)
        _close_compact_dialog()
        st.rerun()
    if c2.button("🔄 Újraírás Pirivel", key="cd_rewrite", **STRETCH):
        with st.spinner("Piri újraírja az összefoglalót…"):
            try:
                new_description, new_content = generate(
                    fix_request.strip() or "Írd meg újra, alaposabban és pontosabban.",
                    f"LEÍRÁS: {description}\n{chat_flow.SUMMARY_SEPARATOR}\n{content}")
            except Exception as e:
                st.error(f"Az újraírás nem sikerült: {e}")
                return
        st.session_state["compact_draft"] = {"signature": signature, "description": new_description,
                                             "content": new_content, "nonce": nonce + 1}
        st.rerun()
    if c3.button("Mégse", key="cd_cancel", **STRETCH):
        # a kézzel átírt szöveget megőrizzük, hogy újranyitáskor ne vesszen el
        st.session_state["compact_draft"] = {**draft, "description": description, "content": content,
                                             "nonce": nonce + 1}
        _close_compact_dialog()
        st.rerun()


def compact_button(project, key):
    if st.button("🧹 Összefoglalás és törlés", key=key,
                 help="Piri összefoglalja az eddigi beszélgetést; jóváhagyásod után az üzenetek törlődnek, "
                      "és Piri az összefoglalóból dolgozik tovább."):
        st.session_state["compact_open"] = project["id"]
        st.rerun()


# --- ELŐZMÉNYEK TÖRLÉSE ÖSSZEFOGLALÓ NÉLKÜL -----------------------------------
def _close_trim_dialog():
    st.session_state.pop("trim_open", None)


def trim_points(messages):
    """Azok a helyek (sorszámok), ahonnan a beszélgetés vége törölhető: a felhasználó kérdései, hogy a
    megmaradó rész mindig teljes kérdés–válasz párokból álljon. Ha nincs ilyen, bármelyik üzenet."""
    with_id = [i for i, m in enumerate(messages) if m.get("id") is not None]
    return [i for i in with_id if messages[i].get("role") == "user"] or with_id


def trim_label(msg):
    text = " ".join(str(msg.get("content") or "").split())
    return f"{fmt_dt(msg.get('created_at'))} – {text[:90]}{'…' if len(text) > 90 else ''}"


@dialog("✂️ Előzmények törlése összefoglaló nélkül", _close_trim_dialog, width="large")
def trim_dialog(project, messages, atts_by_msg):
    points = trim_points(messages)
    if not points:
        st.info("Nincs törölhető üzenet.")
        return
    st.caption("Válaszd ki, melyik kérdésedtől induljon a törlés. Az a kérdés és minden, ami utána jött, "
               "törlődik; ami előtte volt, megmarad. Összefoglaló nem készül.")
    start = st.selectbox("A törlés ettől a kérdéstől indul:", options=points, index=len(points) - 1,
                         format_func=lambda i: trim_label(messages[i]), key=f"trim_start_{len(messages)}")
    doomed = [m for m in messages[start:] if m.get("id") is not None]
    n_atts = sum(len(atts_by_msg.get(m["id"], [])) for m in doomed)
    kept = start
    st.warning(
        f"Véglegesen törlődik {len(doomed)} üzenet" + (f" és {n_atts} csatolt munkaanyag" if n_atts else "")
        + (f"; megmarad az előtte lévő {kept} üzenet." if kept else "; a beszélgetésből semmi nem marad meg.")
        + " A törlés nem vonható vissza. A dokumentumtár és az összefoglalók nem változnak.")
    c1, c2 = st.columns(2)
    if c1.button("🗑️ Igen, törlés", type="primary", key="trim_yes", **STRETCH):
        try:
            db.delete_messages(project["id"], [m["id"] for m in doomed])
        except db.DbError as e:
            st.error(f"A törlés nem sikerült: {e}")
            return
        st.session_state["chat_flash"] = ("success", f"{len(doomed)} üzenet törölve.")
        _close_trim_dialog()
        st.rerun()
    if c2.button("Mégse", key="trim_no", **STRETCH):
        _close_trim_dialog()
        st.rerun()


def trim_button(project, key):
    if st.button("✂️ Törlés összefoglaló nélkül", key=key,
                 help="Egy kiválasztott kérdésedtől a beszélgetés végéig minden törlődik (pl. vakvágány); "
                      "ami előtte volt, megmarad. Összefoglaló nem készül."):
        st.session_state["trim_open"] = project["id"]
        st.rerun()


# --- BESZÉLGETÉS FÜL ---------------------------------------------------------
def show_flash(key):
    flash = st.session_state.pop(key, None)
    if flash:
        getattr(st, flash[0])(flash[1])


def attachment_caption(attachments):
    names = ", ".join(a["name"] for a in attachments)
    return f"📎 {names} (munkaanyag, nem kerül a dokumentumtárba)"


def render_chat_tab(project, readonly, project_docs, messages, atts_by_msg, summaries, tasks=None):
    pid = project["id"]
    docs_by_id = {d["id"]: d for d in project_docs}

    # Felső sor: mely projektdokumentumokat lássa Piri, és az összefoglalás gombja
    col_docs, col_compact, col_trim = st.columns([2.6, 2.8, 3.2], gap="small")
    selected_doc_ids = []
    if project_docs and not readonly:
        doc_ids = [d["id"] for d in project_docs]
        with col_docs.popover(f"📎 Dokumentumok ({len(project_docs)})",
                              help="Mely projektdokumentumokat vegye figyelembe Piri a következő kérdésnél"):
            selected_doc_ids = st.multiselect(
                "Ezeket a projektdokumentumokat veszi figyelembe Piri a következő kérdésnél:",
                options=doc_ids, default=doc_ids, format_func=lambda i: docs_by_id[i]["name"],
                key=f"ctx_{pid}_{'_'.join(map(str, doc_ids))}",
            )
    if messages and not readonly:
        with col_compact:
            compact_button(project, "compact_btn_chat")
        with col_trim:
            trim_button(project, "trim_btn_chat")

    chat_box = st.container(height=FALLBACK_HEIGHT_PX, border=False, key="chat_box")
    with chat_box:
        if not messages:
            st.caption("Az előzményeket összefoglaló váltotta fel (lásd az Összefoglalók fület); Piri azokból dolgozik."
                       if summaries else "Ebben a projektben még nincs üzenet.")
        for i, msg in enumerate(messages):
            with st.chat_message(msg["role"]):
                st.write(msg["content"])
                if msg["role"] == "user":
                    if atts_by_msg.get(msg.get("id")):
                        st.caption(attachment_caption(atts_by_msg[msg["id"]]))
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
        last = messages[-1] if messages else None
        if last and not readonly and last["role"] == "assistant" and not created_names(last["content"]):
            saved_answers = st.session_state.setdefault("saved_answers", {})
            answer_key = f"{pid}:{last.get('id', len(messages))}"
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
                ok, detail = save_document_bytes(pid, file_name, ex.MD_MIME, (body + "\n").encode("utf-8"))
                if ok:
                    saved_answers[answer_key] = file_name
                    st.rerun()
                else:
                    st.error(f"A mentés nem sikerült: {detail}")

    if readonly:
        st.info("Ez a projekt le van zárva, ezért csak olvasható. Kérdezni az oldalsáv „Újranyitás” gombja után lehet.")
        return

    show_flash("chat_flash")
    submitted = st.chat_input("Kérdezz Piritől; képet vagy fájlt is szúrhatsz be a kérdéshez…",
                              accept_file="multiple", file_type=ATTACH_TYPES, key=f"chat_input_{pid}")
    if not submitted:
        return
    question = (submitted if isinstance(submitted, str) else submitted.text or "").strip()
    uploads = [] if isinstance(submitted, str) else list(submitted.files or [])

    # A csatolt munkaanyagok ellenőrzése
    new_files, rejected = [], []
    for f in uploads:
        mime = guess_mime(f.name, f.type)
        limit_mb = MAX_IMAGE_MB if mime.startswith("image/") else MAX_FILE_MB
        if f.size > limit_mb * 1024 * 1024:
            rejected.append(f"{f.name} (nagyobb, mint {limit_mb} MB)")
        else:
            new_files.append((f.name, mime, f.getvalue()))
    if not question and not new_files:
        st.session_state["chat_flash"] = ("error", "Nem csatoltam: " + "; ".join(rejected) + ".")
        st.rerun()
    question = question or "Kérlek, nézd meg a csatolt fájlt."

    with chat_box:
        with st.chat_message("user"):
            st.write(question)
            if new_files:
                st.caption(attachment_caption([{"name": n} for n, _, _ in new_files]))

        # Mentés: az üzenet, majd hozzá kötve a munkaanyagok (ezek nem kerülnek a dokumentumtárba)
        try:
            saved = db.save_message(pid, "user", question)
        except db.DbError as e:
            st.error(f"Az üzenet mentése nem sikerült: {e}")
            return
        current_files = []
        for name, mime, data in new_files:
            try:
                if saved and saved.get("id") is not None:
                    db.save_attachment(pid, saved["id"], name, mime, data)
                current_files.append((name, mime, base64.b64encode(data).decode("ascii")))
            except db.DbError as e:
                rejected.append(f"{name} ({e})")

        # Csak az aktuális projekt kiválasztott dokumentumai kerülhetnek a kérdés mellé
        doc_files = []
        for doc_id in selected_doc_ids:
            doc = docs_by_id.get(doc_id)
            if not doc:
                continue
            try:
                doc_files.append((doc["name"], doc["mime_type"], get_document_content(doc_id)))
            except Exception:
                st.error(f"A(z) {doc['name']} dokumentum nem tölthető be, ezért nem csatoltam.")

        api_messages = build_history(messages, atts_by_msg)
        api_messages.append({"role": "user", "content": user_content(question, doc_files + current_files)})

        # Eszközök: a beépített webes kereső (az Anthropic szerverein fut) és a dokumentumkészítők (nálunk futnak)
        tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}] + ex.TOOLS
        task_events = []
        task_handlers = None
        if tasks is not None:  # feladatkezelés csak akkor, ha a feladatok táblája létezik
            tools = tools + TASK_TOOLS
            task_handlers = make_task_handlers(pid, tasks, task_events)
        taken_names = {d["name"] for d in project_docs}

        def save_created_file(name, mime, data):
            """Piri által készített fájl mentése; siker esetén a tárolt (egyedi) fájlnevet adja vissza."""
            final_name = unique_name(name, taken_names)
            ok, detail = save_document_bytes(pid, final_name, mime, data)
            if ok:
                taken_names.add(final_name)
            return ok, (final_name if ok else detail)

        with st.chat_message("assistant"):
            with st.spinner("Piri elemzi a tartalmat, keres és gondolkodik… (hosszabb dokumentumnál ez több perc is lehet)"):
                answer, sources, created_files, problems = chat_flow.run_conversation(
                    claude_client, MODEL, build_system(summaries, tasks), api_messages, tools, save_created_file,
                    handlers=task_handlers)
            answer = answer or "(Piri most nem adott szöveges választ.)"
            # A hibát az elmentett válaszba is beírjuk, mert az oldal rögtön újratöltődik
            if problems:
                answer += f"\n\n{PROBLEM_MARK} " + " ".join(problems)
            if task_events:
                answer += f"\n\n{TASK_MARK} " + "; ".join(task_events) + " – a **Feladatok** fülön látod."
            if created_files:
                answer += (f"\n\n{CREATED_MARK} " + ", ".join(f"`{n}`" for n in created_files)
                           + " – itt lent és a **Dokumentumok** fülön is letölthető.")
            if sources:
                answer += "\n\n**Források:**\n" + "\n".join(f"- [{title}]({url})" for url, title in sources.items())
            st.write(answer)

    try:
        db.save_message(pid, "assistant", answer)
    except db.DbError as e:
        st.session_state["chat_flash"] = ("error", f"Piri válaszának mentése nem sikerült: {e}")
    if rejected:
        st.session_state["chat_flash"] = ("warning", "Nem csatoltam: " + "; ".join(rejected) + ".")
    st.rerun()


# --- DOKUMENTUMOK FÜL --------------------------------------------------------
def render_docs_tab(project, readonly, project_docs):
    pid = project["id"]
    with st.container(height=FALLBACK_HEIGHT_PX, border=False, key="docs_box"):
        st.caption("A projekt jóváhagyott dokumentumai és a Piri által készített fájlok. Kizárólag ehhez a "
                   "projekthez tartoznak; a beszélgetésbe csatolt munkaanyagok nem ide kerülnek.")
        show_flash("docs_flash")

        if not readonly:
            # A kulcsban lévő számláló nullázza a feltöltőt mentés után, így nem mentjük el kétszer ugyanazt
            nonce = st.session_state.get("uploader_nonce", {}).get(pid, 0)
            uploaded_files = st.file_uploader(
                "Projektdokumentum feltöltése (PDF, Word, Excel, PowerPoint, TXT, PNG, JPG):",
                type=DOC_TYPES,
                accept_multiple_files=True,
                key=f"uploader_{pid}_{nonce}",
            )
            if uploaded_files and st.button("💾 Feltöltés a projekt dokumentumtárába", type="primary"):
                saved, failed = 0, []
                for f in uploaded_files:
                    if f.size > MAX_FILE_MB * 1024 * 1024:
                        failed.append(f"{f.name} (nagyobb, mint {MAX_FILE_MB} MB)")
                        continue
                    ok, detail = save_document_bytes(pid, f.name, guess_mime(f.name, f.type), f.getvalue())
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
                st.session_state.setdefault("uploader_nonce", {})[pid] = nonce + 1
                st.rerun()
            st.divider()

        if not project_docs:
            st.info("Ebben a projektben még nincs dokumentum.")
        for doc in project_docs:
            col_info, col_dl, col_prev, col_del = st.columns([5, 1.7, 1.7, 0.8])
            size_kb = max(1, round((doc.get("size_bytes") or 0) / 1024))
            col_info.write(f"{doc_icon(doc)} **{doc['name']}** · {size_kb} KB · {fmt_dt(doc.get('created_at'))[:10]}")
            want_download = col_dl.checkbox("Letöltés", key=f"dl_{doc['id']}")
            want_preview = col_prev.checkbox("Előnézet", key=f"prev_{doc['id']}")
            if not readonly and col_del.button("🗑️", key=f"del_{doc['id']}", help="Dokumentum törlése a projektből"):
                try:
                    db.delete_document(doc["id"])
                    st.rerun()
                except db.DbError as e:
                    st.error(f"A törlés nem sikerült: {e}")
            if want_download:
                render_downloads(doc)
            if want_preview:
                with st.container(border=True):
                    render_doc_preview(doc)


# --- ÖSSZEFOGLALÓK FÜL -------------------------------------------------------
def _close_sum_delete_dialog():
    st.session_state.pop("sum_delete_open", None)


@dialog("Összefoglaló végleges törlése", _close_sum_delete_dialog)
def sum_delete_dialog(summary):
    st.write(f"Biztosan törlöd a(z) **{fmt_dt(summary['created_at'])}** időpontú összefoglalót?")
    if summary.get("description"):
        st.caption(summary["description"])
    st.warning("A törlés végleges, nem vonható vissza. Amit ez az összefoglaló őrzött a törölt előzményekből, "
               "azt Piri ezután nem fogja tudni.")
    c1, c2 = st.columns(2)
    if c1.button("🗑️ Igen, végleges törlés", type="primary", key="sum_delete_yes", **STRETCH):
        try:
            db.delete_summary(summary["id"])
        except db.DbError as e:
            st.error(f"A törlés nem sikerült: {e}")
            return
        if st.session_state.get("sum_editing") == summary["id"]:
            st.session_state["sum_editing"] = None
        st.session_state["sums_flash"] = ("success", "Az összefoglaló törölve.")
        _close_sum_delete_dialog()
        st.rerun()
    if c2.button("Mégse", key="sum_delete_no", **STRETCH):
        _close_sum_delete_dialog()
        st.rerun()


def render_summaries_tab(project, readonly, summaries, messages):
    with st.container(height=FALLBACK_HEIGHT_PX, border=False, key="sums_box"):
        st.caption("Az összefoglalók a törölt előzmények helyett őrzik a projekt lényegét; Piri mindegyiket "
                   "megkapja. A dátum melletti gombokkal szerkeszthetők és törölhetők.")
        show_flash("sums_flash")
        if not readonly:
            if messages:
                compact_button(project, "compact_btn_tab")
            else:
                st.caption("Új összefoglaló akkor készíthető, ha van beszélgetés a projektben.")
        if not summaries:
            st.info("Ebben a projektben még nincs összefoglaló.")
        edit_nonce = st.session_state.get("sum_edit_nonce", 0)  # mentés után ez zárja be a szerkesztőt
        for s in reversed(summaries):  # a legfrissebb elöl
            st.divider()
            edited = f" · szerkesztve: {fmt_dt(s['updated_at'])}" if s.get("updated_at") else ""
            editing = not readonly and st.session_state.get("sum_editing") == s["id"]
            # a két kis gomb közvetlenül a dátum mellett áll (szerkesztett összefoglalónál hosszabb a felirat)
            col_title, col_edit, col_del, _ = st.columns([4.6 if edited else 2.1, 0.45, 0.45, 5], gap="small",
                                                         vertical_alignment="center")
            col_title.markdown(f"**📋 {fmt_dt(s['created_at'])}**{edited}")
            if not readonly:
                if col_edit.button("✏️", key=f"sum_editbtn_{s['id']}",
                                   help="Szerkesztés bezárása (mentés nélkül)" if editing else "Szerkesztés"):
                    st.session_state["sum_editing"] = None if editing else s["id"]
                    st.session_state["sum_edit_nonce"] = edit_nonce + 1  # a mezők a tárolt szöveggel induljanak
                    st.rerun()
                if col_del.button("🗑️", key=f"sum_delbtn_{s['id']}", help="Összefoglaló törlése"):
                    st.session_state["sum_delete_open"] = s["id"]
                    st.rerun()
            st.write(s.get("description") or "(nincs leírás)")
            with st.expander("Teljes összefoglaló"):
                st.markdown(s["content"])
            if editing:
                new_description = st.text_area("Rövid leírás", value=s.get("description") or "", height=90,
                                               key=f"sum_desc_{s['id']}_{edit_nonce}")
                new_content = st.text_area("Összefoglaló (Markdown)", value=s["content"], height=320,
                                           key=f"sum_content_{s['id']}_{edit_nonce}")
                if st.button("💾 Módosítás mentése", key=f"sum_save_{s['id']}", type="primary"):
                    if not new_content.strip():
                        st.error("Az összefoglaló nem lehet üres.")
                    else:
                        try:
                            db.update_summary(s["id"], new_description.strip(), new_content.strip())
                            st.session_state["sum_edit_nonce"] = edit_nonce + 1
                            st.session_state["sum_editing"] = None
                            st.session_state["sums_flash"] = ("success", "Az összefoglaló módosítva.")
                            st.rerun()
                        except db.DbError as e:
                            st.error(f"A mentés nem sikerült: {e}")


# --- FELADATOK FÜL -----------------------------------------------------------
def _task_apply(task_id, **fields):
    try:
        db.update_task(task_id, **fields)
    except db.DbError as e:
        st.session_state["tasks_flash"] = ("error", f"A módosítás nem sikerült: {e}")


def _task_checked(task_id, key):
    # pipa = a magunk részét elvégeztük (alapból „kész”); pipa nélkül a feladat nyitott
    _task_apply(task_id, status="done" if st.session_state.get(key) else "open")


def _task_status_changed(task_id, key):
    value = st.session_state.get(key)
    if value in TASK_STATUS_LABELS:
        _task_apply(task_id, status=value)


def _close_task_delete_dialog():
    st.session_state.pop("task_delete_open", None)


@dialog("Feladat végleges törlése", _close_task_delete_dialog)
def task_delete_dialog(task):
    st.write(f"Biztosan törlöd ezt a feladatot? **{task_topic(task)} » {task['title']}**")
    st.warning("A törlés végleges, a feladat nyom nélkül eltűnik a listáról (ez a tévesen felvett tételekre való). "
               "Ha csak nem kell elvégezni, és ezt később is látni szeretnéd, inkább állítsd „törölt” vagy "
               "„elavult” állapotra, és írd a megjegyzésbe az okát.")
    c1, c2 = st.columns(2)
    if c1.button("🗑️ Igen, végleges törlés", type="primary", key="task_delete_yes", **STRETCH):
        try:
            db.delete_task(task["id"])
        except db.DbError as e:
            st.error(f"A törlés nem sikerült: {e}")
            return
        st.session_state["tasks_flash"] = ("success", "A feladat törölve.")
        _close_task_delete_dialog()
        st.rerun()
    if c2.button("Mégse", key="task_delete_no", **STRETCH):
        _close_task_delete_dialog()
        st.rerun()


def render_task_row(task, readonly, all_tasks):
    tid = task["id"]
    status = task_status(task)
    nonce = st.session_state.get("task_edit_nonce", 0)
    editing = not readonly and st.session_state.get("task_editing") == tid
    c_chk, c_title, c_status, c_edit, c_del = st.columns([0.35, 6, 2.2, 0.5, 0.5], gap="small",
                                                         vertical_alignment="center")
    # a kulcsban benne van az állapot, így módosítás után a pipa és a lista a friss értéket mutatja
    chk_key = f"task_chk_{tid}_{status}"
    c_chk.checkbox("Elvégezve", value=status != "open", key=chk_key, label_visibility="collapsed",
                   disabled=readonly, on_change=_task_checked, args=(tid, chk_key))
    c_title.write(task["title"])
    if task.get("note"):
        c_title.caption(f"📝 {task['note']}")
    if status == "open":
        c_status.caption("nyitott – nálunk a labda")
    else:
        st_key = f"task_st_{tid}_{status}"
        c_status.selectbox("Állapot", options=list(TASK_CHECKED), index=TASK_CHECKED.index(status),
                           format_func=TASK_STATUS_LABELS.get, key=st_key, label_visibility="collapsed",
                           disabled=readonly, on_change=_task_status_changed, args=(tid, st_key))
    if readonly:
        return
    if c_edit.button("✏️", key=f"task_editbtn_{tid}",
                     help="Szerkesztés bezárása (mentés nélkül)" if editing else "Szöveg, téma és megjegyzés szerkesztése"):
        st.session_state["task_editing"] = None if editing else tid
        st.session_state["task_edit_nonce"] = nonce + 1
        st.rerun()
    if c_del.button("🗑️", key=f"task_delbtn_{tid}", help="Feladat végleges törlése (tévesen felvett tételhez)"):
        st.session_state["task_delete_open"] = tid
        st.rerun()
    if editing:
        e1, e2 = st.columns([1, 2])
        new_topic = e1.text_input("Téma", value=task_topic(task), key=f"task_e_topic_{tid}_{nonce}")
        new_title = e2.text_input("Tennivaló", value=task["title"], key=f"task_e_title_{tid}_{nonce}")
        new_note = st.text_input("Megjegyzés", value=task.get("note") or "", key=f"task_e_note_{tid}_{nonce}",
                                 placeholder="pl. kire várunk, vagy miért nem kell elvégezni")
        if st.button("💾 Mentés", key=f"task_e_save_{tid}", type="primary"):
            if not new_title.strip():
                st.error("A tennivaló szövege nem lehet üres.")
            else:
                others = [t for t in all_tasks if t["id"] != tid]
                try:
                    db.update_task(tid, topic=match_topic(new_topic, others), title=new_title.strip(),
                                   note=new_note.strip())
                except db.DbError as e:
                    st.error(f"A mentés nem sikerült: {e}")
                else:
                    st.session_state["task_editing"] = None
                    st.session_state["task_edit_nonce"] = nonce + 1
                    st.rerun()


def render_tasks_tab(project, readonly, tasks):
    pid = project["id"]
    with st.container(height=FALLBACK_HEIGHT_PX, border=False, key="tasks_box"):
        if tasks is None:
            st.warning("A Feladatok használatához egyszer frissíteni kell az adatbázist: futtasd le a `schema.sql` "
                       "teljes tartalmát a Supabase **SQL Editor** felületén, majd töltsd újra ezt az oldalt. "
                       "A szkript meglévő adatot nem töröl; az alkalmazás többi része addig is működik.")
            try:
                with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql"), encoding="utf-8") as fh:
                    with st.expander("A futtatandó szkript"):
                        st.code(fh.read(), language="sql")
            except OSError:
                pass
            return
        st.caption("Tennivalók témák szerint. A pipa azt jelenti, hogy a magunk részét elvégeztük; mellette az "
                   "állapot: választ várunk, kész, elavult vagy törölt. Piri kérésre vesz fel és módosít feladatot.")
        show_flash("tasks_flash")
        topics = list(dict.fromkeys(task_topic(t) for t in tasks))

        if not readonly:
            with st.expander("➕ Új feladat"):
                with st.form(f"task_add_{pid}", clear_on_submit=True):
                    f1, f2 = st.columns([1, 2])
                    topic = f1.text_input("Téma", placeholder="pl. Vízhálózat")
                    title = f2.text_input("Tennivaló", placeholder="pl. Gépésznek megírni a specifikációt")
                    note = st.text_input("Megjegyzés (nem kötelező)")
                    if st.form_submit_button("Felvétel"):
                        if not title.strip():
                            st.error("Írd be a tennivalót.")
                        else:
                            try:
                                db.add_task(pid, match_topic(topic, tasks), title, note)
                            except db.DbError as e:
                                st.error(f"A felvétel nem sikerült: {e}")
                            else:
                                st.rerun()
                if topics:
                    st.caption("Meglévő témák: " + ", ".join(topics))

        hidden = [t for t in tasks if task_status(t) not in TASK_ACTIVE]
        show_all = bool(hidden) and st.toggle(f"Kész, elavult és törölt tételek is ({len(hidden)})",
                                              key=f"tasks_all_{pid}")
        visible = tasks if show_all else [t for t in tasks if task_status(t) in TASK_ACTIVE]
        if not tasks:
            st.info("Ebben a projektben még nincs feladat. Vegyél fel egyet fent, vagy kérd meg Pirit a beszélgetésben.")
        elif not visible:
            st.info("Nincs nyitott vagy válaszra váró feladat.")
        for topic in topics:
            rows = [t for t in visible if task_topic(t) == topic]
            if not rows:
                continue
            st.divider()
            st.markdown(f"**{topic}**")
            for task in rows:
                render_task_row(task, readonly, tasks)


# --- KERESÉS -----------------------------------------------------------------
def hit_opened(kind, item_id):
    """„Megnyitás” jelölő egy találatnál. Az állapotát külön is megjegyezzük, hogy a projektbe ugrás után
    a találati listához visszatérve ugyanazok a találatok legyenek nyitva."""
    open_hits = st.session_state.setdefault("open_hits", set())
    opened = st.checkbox("Megnyitás", value=(kind, item_id) in open_hits, key=f"hit_{kind}_{item_id}")
    (open_hits.add if opened else open_hits.discard)((kind, item_id))
    return opened


def render_search(active, closed):
    query = st.session_state.get("search_q", "").strip()
    terms = stx.query_terms(query)
    include_closed = bool(st.session_state.get("search_closed"))
    scope = active + (closed if include_closed else [])
    with st.container(height=FALLBACK_HEIGHT_PX, border=False, key="search_box"):
        if not terms:
            st.info("Írj be legalább egy, legalább kétbetűs keresőszót az oldalsáv keresőmezőjébe.")
            return
        try:
            docs, sums = db.search([p["id"] for p in scope], stx.filter_stems(terms))
        except db.DbError as e:
            st.error(f"A keresés nem sikerült: {e}")
            return
        # az adatbázis csak előszűr; a pontos, szavankénti egyeztetés itt történik
        docs = [d for d in docs if stx.matches(f"{d['name']}\n{d.get('content_text') or ''}", terms)]
        sums = [x for x in sums if stx.matches(f"{x.get('description') or ''}\n{x['content']}", terms)]
        where = "az aktív és a lezárt projektekben" if include_closed else "az aktív projektekben"
        if not docs and not sums:
            st.info(f"Nincs találat {where}." + ("" if include_closed or not closed else
                                                " A lezárt projektekben nem kerestem; ehhez pipáld be az oldalsávban."))
            return
        hit_projects = {h["project_id"] for h in docs + sums}
        st.caption(f"{len(docs) + len(sums)} találat {len(hit_projects)} projektben ({where}). Több keresőszónál "
                   "mindegyiknek szerepelnie kell; a ragozott alakokat is megtalálja.")

        for p in scope:
            p_sums = [s for s in sums if s["project_id"] == p["id"]]
            p_docs = [d for d in docs if d["project_id"] == p["id"]]
            if not p_sums and not p_docs:
                continue
            st.divider()
            col_name, col_go = st.columns([6, 2])
            col_name.markdown(f"**📁 {p['name']}**" + ("" if p.get("status") == "active" else " (lezárt)"))
            if col_go.button("➡️ Ugrás a projektre", key=f"goto_{p['id']}", **STRETCH):
                open_project(p["id"])
                st.rerun()

            for s in p_sums:
                snips = stx.snippets(s["content"], terms)
                st.markdown(
                    '<div class="piri-hit"><span class="title">📋 Összefoglaló</span>'
                    f'<span class="meta">{fmt_dt(s["created_at"])}</span>'
                    f'<div class="snip">{stx.highlight(s.get("description") or "", terms)}</div>'
                    + "".join(f'<div class="snip">{sn}</div>' for sn in snips) + "</div>",
                    unsafe_allow_html=True)
                if hit_opened("sum", s["id"]):
                    with st.container(border=True):
                        st.markdown(s["content"])

            p_docs.sort(key=lambda d: -stx.count_hits(f"{d['name']}\n{d.get('content_text') or ''}", terms))
            for d in p_docs:
                text = d.get("content_text") or ""
                snips = stx.snippets(text, terms)
                st.markdown(
                    f'<div class="piri-hit"><span class="title">{doc_icon(d)} {stx.highlight(d["name"], terms)}</span>'
                    f'<span class="meta">{fmt_dt(d.get("created_at"))[:10]}</span>'
                    + "".join(f'<div class="snip">{sn}</div>' for sn in snips) + "</div>",
                    unsafe_allow_html=True)
                if hit_opened("doc", d["id"]):
                    with st.container(border=True):
                        render_downloads(d, key_prefix="hit_")
                        render_doc_preview(d, text=text)


def index_old_documents(rows):
    """A régebben feltöltött dokumentumok szövegének kinyerése, hogy a keresés megtalálja őket."""
    progress = st.progress(0.0, text="Dokumentumok feldolgozása…")
    failed = []
    for n, row in enumerate(rows, 1):
        try:
            data = base64.b64decode(db.get_document_content(row["id"]))
            db.set_document_text(row["id"], row["name"], ex.extract_text(row["name"], row["mime_type"], data))
        except Exception as e:
            failed.append(f"{row['name']} ({e})")
        progress.progress(n / len(rows), text=f"Dokumentumok feldolgozása… {n}/{len(rows)}")
    return failed


# =============================================================================
# AZ OLDAL FELÉPÍTÉSE
# =============================================================================
inject_css()

# Az adatbázis ellenőrzése munkamenetenként egyszer: megvannak-e az új oszlopok és táblák
if not st.session_state.get("schema_ok"):
    missing = db.check_schema()
    if missing:
        st.error("Az adatbázist frissíteni kell, mielőtt az alkalmazás használható. Hiányzik vagy nem érhető el: "
                 + "; ".join(missing))
        st.write("Nyisd meg a Supabase **SQL Editor** felületét, illeszd be az alábbi szkriptet (a `schema.sql` "
                 "fájl tartalmát), futtasd le, majd töltsd újra ezt az oldalt. A szkript meglévő adatot nem töröl.")
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql"), encoding="utf-8") as fh:
                st.code(fh.read(), language="sql")
        except OSError:
            st.warning("A schema.sql fájl nincs az alkalmazás mellett; töltsd fel a repóba.")
        st.stop()
    st.session_state["schema_ok"] = True

try:
    all_projects = db.get_projects()
except db.DbError as e:
    st.error(f"A projektek nem tölthetők be: {e}")
    st.stop()

active_projects = [p for p in all_projects if p.get("status") == "active"]
closed_projects = [p for p in all_projects if p.get("status") != "active"]
projects_by_id = {p["id"]: p for p in all_projects}

# Induláskor a legutóbb használt aktív projekt nyílik meg
if st.session_state.get("current_project_id") not in projects_by_id:
    opened = [p for p in active_projects if p.get("last_opened_at")]
    if opened:
        st.session_state["current_project_id"] = max(opened, key=lambda p: str(p["last_opened_at"]))["id"]
    elif active_projects:
        st.session_state["current_project_id"] = active_projects[0]["id"]
    else:
        st.session_state["current_project_id"] = None
current_project = projects_by_id.get(st.session_state.get("current_project_id"))
current_id = current_project["id"] if current_project else None
current_closed = bool(current_project) and current_project.get("status") != "active"


def _search_changed():
    st.session_state["view"] = "search" if st.session_state.get("search_q", "").strip() else "project"
    st.session_state.pop("open_hits", None)


# --- OLDALSÁV (SIDEBAR) ---
with st.sidebar:
    st.text_input("🔎 Keresés", key="search_q", on_change=_search_changed,
                  placeholder="keresés dokumentumokban és összefoglalókban",
                  help="Az aktív projektek dokumentumaiban és összefoglalóiban keres. Enterrel indul.")
    st.checkbox("Lezárt projektekben is", key="search_closed", on_change=_search_changed)

    if not st.session_state.get("index_done"):
        try:
            unindexed = db.unindexed_documents()
        except db.DbError:
            unindexed = []
        if not unindexed:
            st.session_state["index_done"] = True
        else:
            st.caption(f"{len(unindexed)} régebbi dokumentum tartalmában még nem lehet keresni.")
            if st.button("Feldolgozás a kereséshez", key="index_btn", **STRETCH):
                failed = index_old_documents(unindexed)
                if failed:
                    st.error("Nem sikerült feldolgozni: " + "; ".join(failed[:5]))
                else:
                    st.rerun()

    st.divider()
    st.header("🗂️ Projektek")

    with st.form("project_form", clear_on_submit=True):
        new_project_name = st.text_input("Új téma / projekt neve:")
        submit_button = st.form_submit_button("➕ Projekt létrehozása", **STRETCH)
        if submit_button and new_project_name.strip():
            try:
                created = db.create_project(new_project_name, top_sort_order(all_projects))
            except db.DbError as e:
                st.error(f"A projekt létrehozása nem sikerült: {e}")
            else:
                if created:
                    st.session_state["current_project_id"] = created["id"]
                    st.session_state["view"] = "project"
                st.rerun()

    if active_projects:
        st.subheader("Aktív ügyek")
        for p in active_projects:
            if st.button(p["name"], key=f"proj_{p['id']}", type="primary" if p["id"] == current_id else "secondary",
                         **STRETCH):
                open_project(p["id"])
                st.rerun()
        if current_project and not current_closed:
            st.caption("A kiválasztott projekt:")
            index = [p["id"] for p in active_projects].index(current_id)
            col_up, col_down, col_close = st.columns([1, 1, 2.2])
            try:
                if col_up.button("▲", key="proj_up", help="Feljebb a listában", disabled=index == 0, **STRETCH):
                    move_project(active_projects, current_id, -1)
                    st.rerun()
                if col_down.button("▼", key="proj_down", help="Lejjebb a listában",
                                   disabled=index == len(active_projects) - 1, **STRETCH):
                    move_project(active_projects, current_id, +1)
                    st.rerun()
                if col_close.button("🔒 Lezárás", key="proj_close", **STRETCH,
                                    help="A projekt a lezártak közé kerül: megmarad és olvasható, de nem lehet benne kérdezni."):
                    db.update_project(current_id, status="closed")
                    st.rerun()
            except db.DbError as e:
                st.error(f"A művelet nem sikerült: {e}")
    else:
        st.info("Nincs aktív projekt.")

    if closed_projects:
        with st.expander(f"Lezárt projektek ({len(closed_projects)})", expanded=current_closed):
            for p in closed_projects:
                if st.button(p["name"], key=f"proj_{p['id']}",
                             type="primary" if p["id"] == current_id else "secondary", **STRETCH):
                    open_project(p["id"])
                    st.rerun()
            if current_closed:
                st.caption("A kiválasztott lezárt projekt:")
                col_reopen, col_delete = st.columns(2)
                if col_reopen.button("🔓 Újranyitás", key="proj_reopen", **STRETCH):
                    try:
                        db.update_project(current_id, status="active", sort_order=top_sort_order(all_projects))
                        st.rerun()
                    except db.DbError as e:
                        st.error(f"Az újranyitás nem sikerült: {e}")
                if col_delete.button("🗑️ Törlés", key="proj_delete", **STRETCH):
                    st.session_state["delete_open"] = current_id
                    st.rerun()

# --- FEJLÉC (mindig látható) ---
search_query = st.session_state.get("search_q", "").strip()
in_search = st.session_state.get("view") == "search" and bool(search_query)

if in_search:
    right_html = f'Keresés: <mark>{html.escape(search_query)}</mark>'
elif current_project:
    right_html = html.escape(current_project["name"]) + ('<span class="badge">(lezárt)</span>' if current_closed else "")
else:
    right_html = ""
col_title, col_back = st.columns([6, 2])
col_title.markdown(
    '<div class="piri-header">🤖 Piri AI Munkaállomás'
    + (f'<span class="sep">|</span>{right_html}' if right_html else "") + "</div>",
    unsafe_allow_html=True)
if search_query and not in_search:
    if col_back.button("← Vissza a találatokhoz", key="back_to_search", **STRETCH):
        st.session_state["view"] = "search"
        st.rerun()

# --- FŐKÉPERNYŐ ---
if in_search:
    render_search(active_projects, closed_projects)
elif current_project:
    try:
        project_docs = db.get_documents(current_id)   # csak metaadatok; a tartalom igény szerint töltődik be
        messages = db.get_messages(current_id)
        summaries = db.get_summaries(current_id)
        attachments = db.get_attachments(current_id)
    except db.DbError as e:
        st.error(f"A projekt adatai nem tölthetők be: {e}")
        st.stop()
    try:
        tasks = db.get_tasks(current_id)
    except db.DbError:
        tasks = None  # a feladatok táblája még nincs létrehozva; a Feladatok fül megmondja, mi a teendő
    atts_by_msg = {}
    for att in attachments:
        atts_by_msg.setdefault(att["message_id"], []).append(att)

    if st.session_state.get("delete_open") == current_id and current_closed:
        delete_dialog(current_project)
    elif st.session_state.get("compact_open") == current_id and messages and not current_closed:
        compact_dialog(current_project, messages, atts_by_msg, summaries, project_docs)
    elif st.session_state.get("trim_open") == current_id and messages and not current_closed:
        trim_dialog(current_project, messages, atts_by_msg)
    elif st.session_state.get("sum_delete_open") is not None and not current_closed:
        doomed_summary = next((x for x in summaries if x["id"] == st.session_state["sum_delete_open"]), None)
        if doomed_summary:
            sum_delete_dialog(doomed_summary)
        else:
            _close_sum_delete_dialog()
    elif st.session_state.get("task_delete_open") is not None and tasks and not current_closed:
        doomed_task = next((x for x in tasks if x["id"] == st.session_state["task_delete_open"]), None)
        if doomed_task:
            task_delete_dialog(doomed_task)
        else:
            _close_task_delete_dialog()

    tab_chat, tab_docs, tab_sums, tab_tasks = st.tabs(
        ["💬 Beszélgetés", "📄 Dokumentumok", "📋 Összefoglalók", "✅ Feladatok"])  # állandó feliratok, különben fülváltás lenne
    with tab_chat:
        render_chat_tab(current_project, current_closed, project_docs, messages, atts_by_msg, summaries, tasks)
    with tab_docs:
        render_docs_tab(current_project, current_closed, project_docs)
    with tab_sums:
        render_summaries_tab(current_project, current_closed, summaries, messages)
    with tab_tasks:
        render_tasks_tab(current_project, current_closed, tasks)
else:
    st.write("### 👈 Kezdéshez válassz vagy hozz létre egy projektet a bal oldali sávban!")

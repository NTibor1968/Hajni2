import streamlit as st
from supabase import create_client, Client
from anthropic import Anthropic

try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]
except Exception as e:
    st.error("Hiba! Hiányzik a .streamlit/secrets.toml fájl vagy hibásak a kulcsok.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
claude_client = Anthropic(api_key=ANTHROPIC_API_KEY)

st.set_page_config(page_title="Hajni2 Asszisztens", layout="wide")

def get_projects(status="active"):
    response = supabase.table("projects").select("*").eq("status", status).order("created_at", desc=True).execute()
    return response.data

def create_project(name):
    if name.strip():
        supabase.table("projects").insert({"name": name, "status": "active"}).execute()
        st.rerun()

def archive_project(project_id):
    supabase.table("projects").update({"status": "archived"}).eq("id", project_id).execute()
    st.rerun()

def get_messages(project_id):
    response = supabase.table("messages").select("*").eq("project_id", project_id).order("created_at", desc=False).execute()
    return response.data

def save_message(project_id, role, content):
    supabase.table("messages").insert({"project_id": project_id, "role": role, "content": content}).execute()

st.title("🤖 Hajni2 AI Munkaállomás")

with st.sidebar:
    st.header("🗂️ Projektek")
    new_project_name = st.text_input("Új téma / projekt neve:", key="new_proj_input")
    if st.button("➕ Projekt létrehozása", use_container_width=True):
        create_project(new_project_name)
    st.divider()
    active_projektek = get_projects("active")
    if active_projektek:
        st.subheader("Aktív ügyek")
        project_options = {p["name"]: p["id"] for p in active_projektek}
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
        for msg in messages:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])
        if user_input := st.chat_input("Kérdezz, elemezzünk törvényt..."):
            with st.chat_message("user"):
                st.write(user_input)
            save_message(current_project_id, "user", user_input)
            context_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
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



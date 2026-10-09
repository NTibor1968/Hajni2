import streamlit as st
import requests

# Kulcsok betöltése és letisztítása
try:
    SUPABASE_URL = str(st.secrets["SUPABASE_URL"]).strip().strip("'").strip('"')
    SUPABASE_KEY = str(st.secrets["SUPABASE_KEY"]).strip().strip("'").strip('"')
    ANTHROPIC_API_KEY = str(st.secrets["ANTHROPIC_API_KEY"]).strip().strip("'").strip('"')
except Exception as e:
    st.error(f"Biztonsági hiba! Hiányzik a secrets.toml vagy hibásak a kulcsok: {e}")
    st.stop()

# Supabase hálózati fejléc
headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

st.set_page_config(page_title="Hajni2 Asszisztens", layout="wide")
st.title("🤖 Hajni2 AI Munkaállomás")

# --- ADATBÁZIS LEKÉRÉS ---
active_projects = []
try:
    url = f"{SUPABASE_URL}/rest/v1/projects?status=eq.active&order=created_at.desc"
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        active_projects = res.json()
    else:
        st.error(f"Szerver hiba a listázáskor! Kód: {res.status_code}, Válasz: {res.text}")
except Exception as e:
    st.error(f"Kapcsolódási hiba a Supabase-hez: {e}")

# --- OLDALSÁV (SIDEBAR) ---
with st.sidebar:
    st.header("🗂️ Projektek")
    
    new_project_name = st.text_input("Új téma / projekt neve:", key="new_proj_input")
    
    if st.button("➕ Projekt létrehozása", use_container_width=True):
        if new_project_name.strip():
            # Ellenőrizzük, létezik-e már ilyen nevű projekt a helyi listában
            if any(p.get("name") == new_project_name.strip() for p in active_projects):
                st.warning("Ilyen nevű projekt már létezik az adatbázisban!")
            else:
                post_url = f"{SUPABASE_URL}/rest/v1/projects"
                post_res = requests.post(post_url, headers=headers, json={"name": new_project_name.strip(), "status": "active"})
                
                # HA SIKERES (200 vagy 201), AKKOR ÚJRAINDÍTJUK AZ OLDALT
                if post_res.status_code in:
                    st.success("Projekt sikeresen mentve!")
                    st.rerun()
                else:
                    # HA HIBA VAN, AZT KIÍRJUK A FŐKÉPERNYŐRE
                    st.session_state["db_error"] = f"Supabase Mentési Hiba! Kód: {post_res.status_code}, Üzenet: {post_res.text}"
                    st.rerun()

    st.divider()

    # Megjelenítés az oldalsávban
    if active_projects:
        st.subheader("Aktív ügyek")
        project_options = {p["name"]: p["id"] for p in active_projects if "name" in p}
        valasztott_nev = st.radio("Válassz projektet:", list(project_options.keys()))
        current_project_id = project_options[valasztott_nev] if valasztott_nev else None
    else:
        st.info("Nincs aktív projekt az adatbázisban. Hozz létre egyet fent!")
        current_project_id = None

# --- FŐKÉPERNYŐ HIBAJELZÉS ÉS MEGJELENÍTÉS ---
if "db_error" in st.session_state:
    st.error(st.session_state["db_error"])
    del st.session_state["db_error"]

if current_project_id:
    st.write(f"### Kijelölve: {valasztott_nev}")
    st.info("Az adatbázis kapcsolat működik! Következő lépés a chat indítása.")
else:
    st.write("### 👈 Kezdéshez válassz vagy hozz létre egy projektet a bal oldali sávban!")

"""Adatbázis-műveletek a Supabase REST felületén (PostgREST) keresztül. Streamlittől független.

Olvasásnál és írásnál is DbError keletkezik, ha a kérés nem sikerül: így a felület mindig meg tudja
mondani, mi a baj, és nem mutat üres listát hiba helyett."""
import base64
from datetime import datetime, timezone

import requests

import search_tools as stx

_url = None
_headers = None
TIMEOUT = 60

# Ezeknek az oszlopoknak és tábláknak létezniük kell (schema.sql hozza létre őket)
REQUIRED = [
    ("projects", "id,name,status,created_at,sort_order,last_opened_at"),
    ("messages", "id,project_id,role,content,created_at"),
    ("project_documents", "id,project_id,name,mime_type,size_bytes,created_at,content_text,search_text"),
    ("project_summaries", "id,project_id,description,content,search_text,created_at,updated_at"),
    ("message_attachments", "id,project_id,message_id,name,mime_type,size_bytes,created_at"),
]


class DbError(Exception):
    pass


# Jogosultsági szabály (RLS) mellett a tiltott módosítás vagy törlés nem ad hibát, csak nulla sort érint,
# ezért ezt külön ellenőrizzük, hogy az alkalmazás ne állítson olyat, ami nem történt meg.
NOT_APPLIED = "az adatbázis nem hajtotta végre a műveletet (valószínűleg jogosultság hiányzik); futtasd le a schema.sql-t."


def init(url, key):
    global _url, _headers
    _url = url.rstrip("/")
    _headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _explain(res):
    if "42501" in res.text or "row-level security" in res.text:
        return "a Supabase jogosultsági szabálya (RLS) elutasította a műveletet; futtasd le a schema.sql-t."
    return f"{res.status_code}: {res.text[:300]}"


def _request(method, table, params=None, json=None, prefer="return=representation"):
    try:
        res = requests.request(method, f"{_url}/rest/v1/{table}", headers={**_headers, "Prefer": prefer},
                               params=params, json=json, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise DbError(f"Az adatbázis nem érhető el: {e}") from e
    if res.status_code not in (200, 201, 204):
        raise DbError(_explain(res))
    if prefer == "return=minimal" or not res.content:
        return []
    return res.json()


def _in(values):
    return "in.(" + ",".join(str(v) for v in values) + ")"


def _chunks(values, size=40):
    values = list(values)
    for i in range(0, len(values), size):
        yield values[i:i + size]


def check_schema():
    """Azoknak a tábláknak a listája, amelyekből hiányzik valami (üres lista = minden rendben)."""
    missing = []
    for table, columns in REQUIRED:
        try:
            _request("GET", table, {"select": columns, "limit": 1})
        except DbError as e:
            missing.append(f"{table} ({e})")
    return missing


# --- Projektek -------------------------------------------------------------
def get_projects():
    """Minden projekt a kézi sorrend szerint (ahol nincs sorrend, ott a legújabb elöl)."""
    return _request("GET", "projects", {"select": "*", "order": "sort_order.asc.nullslast,created_at.desc"})


def create_project(name, sort_order):
    rows = _request("POST", "projects", json={"name": name.strip(), "status": "active", "sort_order": sort_order,
                                               "last_opened_at": now_iso()})
    return rows[0] if rows else None


def update_project(project_id, **fields):
    rows = _request("PATCH", "projects", {"id": f"eq.{project_id}"}, json=fields)
    if not rows:
        raise DbError(NOT_APPLIED)
    return rows[0]


def delete_project(project_id):
    """A projekt és minden hozzá tartozó adat végleges törlése."""
    for table in ("message_attachments", "messages", "project_documents", "project_summaries"):
        _request("DELETE", table, {"project_id": f"eq.{project_id}"}, prefer="return=minimal")
    _request("DELETE", "projects", {"id": f"eq.{project_id}"}, prefer="return=minimal")
    if _request("GET", "projects", {"id": f"eq.{project_id}", "select": "id"}):
        raise DbError(NOT_APPLIED)


# --- Üzenetek --------------------------------------------------------------
def get_messages(project_id):
    return _request("GET", "messages", {"project_id": f"eq.{project_id}", "order": "created_at.asc"})


def save_message(project_id, role, content):
    rows = _request("POST", "messages", json={"project_id": project_id, "role": role, "content": content})
    return rows[0] if rows else None


def delete_messages(project_id, message_ids):
    """A megadott üzenetek és a hozzájuk csatolt munkaanyagok törlése."""
    for chunk in _chunks(message_ids):
        _request("DELETE", "message_attachments", {"project_id": f"eq.{project_id}", "message_id": _in(chunk)},
                 prefer="return=minimal")
    for chunk in _chunks(message_ids):
        _request("DELETE", "messages", {"project_id": f"eq.{project_id}", "id": _in(chunk)}, prefer="return=minimal")
        if _request("GET", "messages", {"project_id": f"eq.{project_id}", "id": _in(chunk), "select": "id"}):
            raise DbError(NOT_APPLIED)


# --- Beszélgetésbe csatolt munkaanyagok ---------------------------------------
def get_attachments(project_id):
    """A projekt csatolt munkaanyagai tartalom nélkül."""
    return _request("GET", "message_attachments", {
        "project_id": f"eq.{project_id}", "select": "id,message_id,name,mime_type,size_bytes,created_at",
        "order": "id.asc"})


def save_attachment(project_id, message_id, name, mime_type, data):
    _request("POST", "message_attachments", json={
        "project_id": project_id, "message_id": message_id, "name": name, "mime_type": mime_type,
        "size_bytes": len(data), "content_b64": base64.b64encode(data).decode("ascii"),
    }, prefer="return=minimal")


def get_attachment_content(attachment_id):
    rows = _request("GET", "message_attachments", {"id": f"eq.{attachment_id}", "select": "content_b64"})
    if not rows:
        raise DbError("A csatolt fájl nem található.")
    return rows[0]["content_b64"]


# --- Dokumentumtár ---------------------------------------------------------
DOC_META = "id,project_id,name,mime_type,size_bytes,created_at"


def get_documents(project_id):
    """Az adott projekt dokumentumainak listája (tartalom nélkül), a legújabb elöl."""
    return _request("GET", "project_documents", {
        "project_id": f"eq.{project_id}", "select": DOC_META, "order": "created_at.desc"})


def save_document(project_id, name, mime_type, data, text):
    """Dokumentum mentése a kereséshez kinyert szöveggel együtt (text lehet None, pl. képnél)."""
    _request("POST", "project_documents", json={
        "project_id": project_id, "name": name, "mime_type": mime_type, "size_bytes": len(data),
        "content_b64": base64.b64encode(data).decode("ascii"),
        "content_text": stx.clean_text(text), "search_text": stx.build_search_text(name, text),
    }, prefer="return=minimal")


def get_document_content(doc_id):
    rows = _request("GET", "project_documents", {"id": f"eq.{doc_id}", "select": "content_b64"})
    if not rows:
        raise DbError("A dokumentum nem található.")
    return rows[0]["content_b64"]


def get_document_text(doc_id):
    rows = _request("GET", "project_documents", {"id": f"eq.{doc_id}", "select": "content_text"})
    return (rows[0].get("content_text") or "") if rows else ""


def delete_document(doc_id):
    _request("DELETE", "project_documents", {"id": f"eq.{doc_id}"}, prefer="return=minimal")


def unindexed_documents():
    """A kereséshez még fel nem dolgozott (régebben feltöltött) dokumentumok."""
    return _request("GET", "project_documents", {"search_text": "is.null", "select": "id,name,mime_type"})


def set_document_text(doc_id, name, text):
    rows = _request("PATCH", "project_documents", {"id": f"eq.{doc_id}"}, json={
        "content_text": stx.clean_text(text), "search_text": stx.build_search_text(name, text)})
    if not rows:
        raise DbError(NOT_APPLIED)


# --- Összefoglalók ---------------------------------------------------------
def get_summaries(project_id):
    """A projekt összefoglalói időrendben (a legrégebbi elöl)."""
    return _request("GET", "project_summaries", {
        "project_id": f"eq.{project_id}", "select": "id,project_id,description,content,created_at,updated_at",
        "order": "created_at.asc"})


def add_summary(project_id, description, content):
    rows = _request("POST", "project_summaries", json={
        "project_id": project_id, "description": description, "content": content,
        "search_text": stx.build_search_text(description, content)})
    if not rows:
        raise DbError("az összefoglaló mentését az adatbázis nem igazolta vissza.")
    return rows[0]


def update_summary(summary_id, description, content):
    rows = _request("PATCH", "project_summaries", {"id": f"eq.{summary_id}"}, json={
        "description": description, "content": content, "updated_at": now_iso(),
        "search_text": stx.build_search_text(description, content)})
    if not rows:
        raise DbError(NOT_APPLIED)


def delete_summary(summary_id):
    _request("DELETE", "project_summaries", {"id": f"eq.{summary_id}"}, prefer="return=minimal")
    if _request("GET", "project_summaries", {"id": f"eq.{summary_id}", "select": "id"}):
        raise DbError(NOT_APPLIED)


# --- Keresés ---------------------------------------------------------------
def search(project_ids, stems, limit=60):
    """Előszűrés: dokumentumok és összefoglalók, amelyek szövegében minden tő előfordul (a pontos, szavankénti
    egyeztetést a search_tools végzi). Visszaad: (dokumentumok, összefoglalók); a dokumentumoknál a kinyert
    szöveg is benne van."""
    if not project_ids or not stems:
        return [], []
    condition = "(" + ",".join(f"search_text.ilike.*{s}*" for s in stems) + ")"
    docs, sums = [], []
    for chunk in _chunks(project_ids):
        base = {"project_id": _in(chunk), "and": condition, "order": "created_at.desc", "limit": limit}
        docs += _request("GET", "project_documents", {**base, "select": DOC_META + ",content_text"})
        sums += _request("GET", "project_summaries", {
            **base, "select": "id,project_id,description,content,created_at,updated_at"})
    return docs, sums

-- Piri AI Munkaállomás – adatbázis-frissítés
-- Futtatás: Supabase → SQL Editor → illeszd be az egészet → Run.
-- Többször is lefuttatható, meglévő adatot nem töröl és nem módosít.

-- 1. Projektek: kézi sorrend és a legutóbbi megnyitás ideje
alter table public.projects add column if not exists sort_order double precision;
alter table public.projects add column if not exists last_opened_at timestamptz;

-- 1/b. Projektek állapota: a lezáráshoz a "closed" értéket is engedni kell.
--    A régi projects_status_check szabály ezt nem engedte (23514-es hiba lezáráskor).
alter table public.projects drop constraint if exists projects_status_check;
do $$
begin
  if not exists (select 1 from public.projects where status is null or status not in ('active', 'closed')) then
    alter table public.projects
      add constraint projects_status_check check (status in ('active', 'closed'));
  end if;
end $$;

-- 2. Dokumentumok: a fájlból kinyert szöveg (content_text) és annak kereshető,
--    kisbetűs, ékezet nélküli változata (search_text; amíg üres, a dokumentum nincs feldolgozva)
alter table public.project_documents add column if not exists content_text text;
alter table public.project_documents add column if not exists search_text text;

-- 3. Új táblák: összefoglalók, a beszélgetésbe csatolt munkaanyagok és a feladatok.
--    A project_id és a message_id típusa automatikusan a meglévő táblákéhoz igazodik.
do $$
declare
  pid_type text;
  mid_type text;
begin
  select format_type(a.atttypid, a.atttypmod) into pid_type
    from pg_attribute a
   where a.attrelid = 'public.projects'::regclass and a.attname = 'id' and not a.attisdropped;
  select format_type(a.atttypid, a.atttypmod) into mid_type
    from pg_attribute a
   where a.attrelid = 'public.messages'::regclass and a.attname = 'id' and not a.attisdropped;
  if pid_type is null or mid_type is null then
    raise exception 'A projects vagy a messages táblában nincs id oszlop.';
  end if;

  execute format(
    'create table if not exists public.project_summaries (
       id bigint generated always as identity primary key,
       project_id %s not null,
       description text not null default '''',
       content text not null,
       search_text text,
       created_at timestamptz not null default now(),
       updated_at timestamptz
     )', pid_type);

  execute format(
    'create table if not exists public.message_attachments (
       id bigint generated always as identity primary key,
       project_id %s not null,
       message_id %s not null,
       name text not null,
       mime_type text not null,
       size_bytes bigint not null default 0,
       content_b64 text not null,
       created_at timestamptz not null default now()
     )', pid_type, mid_type);

  -- Feladatok: téma » tennivaló, állapottal és megjegyzéssel
  -- (állapotok: open = nyitott, waiting = választ várunk, done = kész, obsolete = elavult, cancelled = törölt)
  execute format(
    'create table if not exists public.project_tasks (
       id bigint generated always as identity primary key,
       project_id %s not null,
       topic text not null default '''',
       title text not null,
       status text not null default ''open'',
       note text not null default '''',
       created_at timestamptz not null default now(),
       updated_at timestamptz
     )', pid_type);
end $$;

create index if not exists project_summaries_project_idx on public.project_summaries (project_id, created_at);
create index if not exists message_attachments_project_idx on public.message_attachments (project_id);
create index if not exists message_attachments_message_idx on public.message_attachments (message_id);
create index if not exists project_tasks_project_idx on public.project_tasks (project_id, created_at);

-- 4. Jogosultságok: az alkalmazás kulcsa olvashassa és írhassa az öt táblát.
--    (Az új funkciókhoz a régi tábláknál is kell módosítás és törlés: sorrend, lezárás,
--    projekt törlése, előzmények törlése, dokumentumok feldolgozása a kereséshez.)
alter table public.project_summaries enable row level security;
alter table public.message_attachments enable row level security;
alter table public.project_tasks enable row level security;

grant select, insert, update, delete
   on public.projects, public.messages, public.project_documents,
      public.project_summaries, public.message_attachments, public.project_tasks
   to anon, authenticated, service_role;

do $$
declare
  t text;
begin
  foreach t in array array['projects', 'messages', 'project_documents', 'project_summaries', 'message_attachments', 'project_tasks']
  loop
    execute format('drop policy if exists piri_app_access on public.%I', t);
    execute format(
      'create policy piri_app_access on public.%I for all to anon, authenticated using (true) with check (true)', t);
  end loop;
end $$;

-- 5. A Supabase API azonnal vegye észre az új oszlopokat és táblákat
notify pgrst, 'reload schema';

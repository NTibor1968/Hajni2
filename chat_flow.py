"""Egy chatkérdés teljes lebonyolítása: modellhívás, szerveroldali keresés folytatása (pause_turn)
és a dokumentumkészítő eszközök végrehajtása (tool_use). Streamlittől független, ezért tesztelhető."""
import export_tools as ex

MAX_FILE_BYTES = 10 * 1024 * 1024

# Ezt kapja Piri, ha a fájl tartalma nem fért bele egyetlen válaszba (a fájl ilyenkor nem készül el).
TRUNCATED_NOTE = (
    "[Az alkalmazás üzenete] A fájl NEM készült el: a tartalma túl hosszú volt egyetlen válaszhoz, ezért "
    "az eszközhívás megszakadt. Készítsd el újra úgy, hogy több, egyenként rövidebb fájlra bontod "
    "(pl. „… – 1. rész”, „… – 2. rész”), válaszonként egyetlen eszközhívással, vagy készíts tömörebb változatot."
)


def _call_model(client, **kwargs):
    """Streamelve hívjuk a modellt: hosszú dokumentumnál a nem streamelt hívás időtúllépésbe futna,
    nagy max_tokens értéknél pedig az SDK el sem indítja."""
    with client.messages.stream(**kwargs) as stream:
        return stream.get_final_message()


def _execute_tool(block, save_file, created, problems, handlers=None):
    """Egy tool_use blokk végrehajtása; mindig tool_result blokkot ad vissza."""
    def result(text, error=False):
        r = {"type": "tool_result", "tool_use_id": block.id, "content": text}
        if error:
            r["is_error"] = True
        return r

    if handlers and block.name in handlers:  # nem fájlt készítő eszköz (pl. feladatok): szöveges eredményt ad
        try:
            return result(str(handlers[block.name](block.input or {})))
        except Exception as e:
            return result(f"Hiba: {e}", error=True)

    try:
        name, mime, data = ex.run_tool(block.name, block.input)
        if len(data) > MAX_FILE_BYTES:
            raise ex.ToolError("A kész fájl túl nagy (legfeljebb 10 MB lehet). Készíts kisebbet vagy oszd több fájlra.")
        ok, info = save_file(name, mime, data)  # siker esetén info = a tárolt fájlnév, hiba esetén a hiba oka
        if not ok:
            problems.append(f"A(z) {name} fájl elkészült, de a mentése nem sikerült: {info}")
            return result(f"A fájl elkészült, de a mentése a dokumentumtárba nem sikerült: {info} "
                          "Ne próbáld újra; mondd meg a felhasználónak, hogy a mentés nem sikerült.", error=True)
        name = info or name
        created.append(name)
        return result(f"Elkészült és mentve a projekt dokumentumtárába: {name}. "
                      "A letöltőgombot az alkalmazás a válaszod alá teszi.")
    except ex.ToolError as e:
        return result(f"Hiba: {e} Javítsd, és hívd meg újra az eszközt.", error=True)
    except Exception as e:  # váratlan hiba ne állítsa meg az egész beszélgetést
        return result(f"Váratlan hiba a fájl készítésekor: {e}", error=True)


def run_conversation(client, model, system, api_messages, tools, save_file, max_rounds=8, max_tokens=64000,
                     handlers=None):
    """Visszaad: (válasz szövege, források {url: cím}, elkészült fájlnevek, problémák listája).

    A problémák a felhasználónak szóló, érthető mondatok arról, ha egy fájl nem készült el vagy nem lett
    elmentve; így soha nem marad észrevétlen, ha Piri nem tudott dokumentumot leadni."""
    parts, sources, created, problems = [], {}, [], []
    sep = ""
    retried_truncation = False
    for _ in range(max_rounds):
        try:
            response = _call_model(
                client, model=model, max_tokens=max_tokens, system=system, messages=api_messages, tools=tools
            )
        except Exception as e:  # hálózati vagy API-hiba: a már elkészült fájlokról így is beszámolunk
            problems.append(f"Hiba történt a modell hívásakor: {e}")
            break

        # Az új modellek gondolkodási (thinking) és keresési blokkot is visszaadhatnak: csak a szöveget vesszük
        text = []
        for block in response.content:
            if block.type == "text":
                text.append(block.text)
                for citation in getattr(block, "citations", None) or []:
                    if getattr(citation, "url", None):
                        sources[citation.url] = citation.title or citation.url
        if text:
            parts.append(sep + "".join(text))

        if response.stop_reason == "pause_turn":  # a szerveroldali keresés megszakadt, folytatjuk
            api_messages.append({"role": "assistant", "content": response.content})
            sep = ""
            continue

        if response.stop_reason == "tool_use":  # dokumentumkészítő eszköz: végrehajtjuk, és visszaadjuk az eredményt
            results = [_execute_tool(b, save_file, created, problems, handlers)
                       for b in response.content if b.type == "tool_use"]
            if not results:
                break
            api_messages.append({"role": "assistant", "content": response.content})
            api_messages.append({"role": "user", "content": results})
            sep = "\n\n"
            continue

        if response.stop_reason == "max_tokens":
            # A válasz elérte a hosszkorlátot. Ha épp fájlt készített, a félbemaradt eszközhívás használhatatlan:
            # egyszer megkérjük Pirit, hogy bontsa részekre; a csonka blokkot nem küldjük vissza.
            cut_tool = any(b.type == "tool_use" for b in response.content)
            if cut_tool and not retried_truncation:
                retried_truncation = True
                kept = "".join(text).strip()
                if kept:
                    api_messages.append({"role": "assistant", "content": kept})
                api_messages.append({"role": "user", "content": TRUNCATED_NOTE})
                sep = "\n\n"
                continue
            problems.append(
                "A fájl nem készült el, mert a tartalma túl hosszú volt egyetlen válaszhoz. "
                "Kérd Piritől részletekben (pl. fejezetenként külön fájlban)." if cut_tool else
                "A válasz elérte a hosszkorlátot, ezért a vége lemaradt. Kérd Piritől a folytatást."
            )
        break
    else:
        if not created:
            problems.append("Piri többszöri próbálkozásra sem tudta befejezni a feladatot. Próbáld meg újra, egyszerűbb kéréssel.")

    return "".join(parts).strip(), sources, created, list(dict.fromkeys(problems))


# ---------------------------------------------------------------------------
# Összefoglaló készítése az előzmények törlése előtt
# ---------------------------------------------------------------------------
SUMMARY_SEPARATOR = "====="

SUMMARY_INSTRUCTION = (
    "[Az alkalmazás kérése] Készíts összefoglalót a fenti beszélgetésről. A beszélgetés üzenetei és a "
    "hozzájuk csatolt munkaanyagok (képek, fájlok) ezután véglegesen törlődnek, és a jövőben kizárólag "
    "az összefoglalókból fogsz dolgozni. Ezért rögzíts minden olyan részletet, amire később szükség lehet; "
    "ami kimarad, az elvész. Ne általánosságokat írj, hanem konkrétumokat: neveket, összegeket, dátumokat, "
    "jogszabályhelyeket. Ne találj ki semmit, ami a beszélgetésben nem szerepelt.\n\n"
    "A válaszod pontosan ebben a formában legyen, más szöveg nélkül:\n"
    "LEÍRÁS: <2–3 mondat arról, miről szólt ez a beszélgetésszakasz és mi lett az eredménye>\n"
    f"{SUMMARY_SEPARATOR}\n"
    "<az összefoglaló Markdownban, az alábbi szakaszokkal; az üres szakaszt hagyd ki>\n"
    "## Tények és számok\n## Döntések és megállapítások\n## Kijavított tévedések\n"
    "## Nyitott kérdések és teendők\n## Elkészült fájlok\n## Csatolt munkaanyagok lényege\n\n"
    "A „Kijavított tévedések” szakaszba azt írd, amit a beszélgetés során rosszul mondtál és később "
    "helyesbítettél (a helyes változattal), hogy többé ne ismételd meg. A korábbi összefoglalók tartalmát "
    "ne ismételd meg, csak az azóta történteket foglald össze."
)


def parse_summary(text):
    """A modell válaszából (leírás, összefoglaló). Ha a formátum nem stimmel, a teljes szöveg az összefoglaló."""
    text = str(text or "").strip()
    head, sep, body = text.partition(SUMMARY_SEPARATOR)
    if sep and body.strip():
        description = head.strip()
        for prefix in ("LEÍRÁS:", "Leírás:", "**LEÍRÁS:**", "**Leírás:**"):
            if description.startswith(prefix):
                description = description[len(prefix):].strip()
        return " ".join(description.split()), body.strip().lstrip("=").strip()
    plain = " ".join(text.replace("#", " ").replace("*", " ").split())
    return plain[:300] + ("…" if len(plain) > 300 else ""), text


def summarize(client, model, system, api_messages, doc_names=(), fix_request="", previous_draft="", max_tokens=16000):
    """Összefoglaló a beszélgetésről. Visszaad: (rövid leírás, összefoglaló Markdownban).
    A fix_request a felhasználó javítási kérése az előző tervezethez (previous_draft)."""
    instruction = SUMMARY_INSTRUCTION
    if doc_names:
        instruction += ("\n\nA projekt dokumentumtárában lévő fájlok (ezek megmaradnak, a tartalmukat nem kell "
                        "leírnod, csak hivatkozz rájuk név szerint, ahol kell): " + ", ".join(doc_names))
    if previous_draft and fix_request:
        instruction += (f"\n\nAz előző tervezeted ez volt:\n<tervezet>\n{previous_draft}\n</tervezet>\n\n"
                        f"A felhasználó ezt kéri rajta javítani: {fix_request}\n"
                        "Írd meg újra a teljes összefoglalót a javítással, ugyanabban a formában.")
    messages = list(api_messages) + [{"role": "user", "content": instruction}]
    response = _call_model(client, model=model, max_tokens=max_tokens, system=system, messages=messages)
    text = "".join(b.text for b in response.content if b.type == "text")
    if not text.strip():
        raise RuntimeError("Piri nem adott vissza összefoglalót.")
    description, content = parse_summary(text)
    if response.stop_reason == "max_tokens":
        content += "\n\n*(Az összefoglaló elérte a hosszkorlátot, a vége hiányozhat. Egészítsd ki, mielőtt jóváhagyod.)*"
    return description, content

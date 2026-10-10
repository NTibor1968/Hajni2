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


def _execute_tool(block, save_file, created, problems):
    """Egy tool_use blokk végrehajtása; mindig tool_result blokkot ad vissza."""
    def result(text, error=False):
        r = {"type": "tool_result", "tool_use_id": block.id, "content": text}
        if error:
            r["is_error"] = True
        return r

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


def run_conversation(client, model, system, api_messages, tools, save_file, max_rounds=8, max_tokens=64000):
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
            results = [_execute_tool(b, save_file, created, problems)
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

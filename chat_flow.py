"""Egy chatkérdés teljes lebonyolítása: modellhívás, szerveroldali keresés folytatása (pause_turn)
és a dokumentumkészítő eszközök végrehajtása (tool_use). Streamlittől független, ezért tesztelhető."""
import export_tools as ex

MAX_FILE_BYTES = 10 * 1024 * 1024


def _execute_tool(block, save_file, created):
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
        ok, detail = save_file(name, mime, data)
        if not ok:
            return result(f"A fájl elkészült, de a mentése nem sikerült: {detail}", error=True)
        created.append(name)
        return result(f"Elkészült és mentve a projekt dokumentumtárába: {name}. "
                      "A felhasználó a Dokumentumok fülön tudja letölteni.")
    except ex.ToolError as e:
        return result(f"Hiba: {e} Javítsd, és hívd meg újra az eszközt.", error=True)
    except Exception as e:  # váratlan hiba ne állítsa meg az egész beszélgetést
        return result(f"Váratlan hiba a fájl készítésekor: {e}", error=True)


def run_conversation(client, model, system, api_messages, tools, save_file, max_rounds=8, max_tokens=16000):
    """Visszaad: (válasz szövege, források {url: cím}, elkészült fájlnevek)."""
    parts, sources, created = [], {}, []
    sep = ""
    for _ in range(max_rounds):
        response = client.messages.create(
            model=model, max_tokens=max_tokens, system=system, messages=api_messages, tools=tools
        )

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
            results = [_execute_tool(b, save_file, created) for b in response.content if b.type == "tool_use"]
            if not results:
                break
            api_messages.append({"role": "assistant", "content": response.content})
            api_messages.append({"role": "user", "content": results})
            sep = "\n\n"
            continue

        break
    return "".join(parts).strip(), sources, created

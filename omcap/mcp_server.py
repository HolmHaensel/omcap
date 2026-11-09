"""MCP server (stdio) for the E-M1, standard library only.

Writing tools only work if OMCAP_ALLOW_WRITE=1 is set.
Claude Desktop additionally asks before every tool call.
"""
import base64
import json
import os
import sys
import time

from .camera import Camera, CameraError, WriteBlocked
from .liveview import LiveView

CAPTURES = os.path.join(os.getcwd(), "captures")  # shots in the current folder
LV_PORT = 5555

cam = Camera(os.environ.get("OMCAP_HOST", "192.168.0.10"),
             allow_write=os.environ.get("OMCAP_ALLOW_WRITE") == "1")


def _img(data):
    return [{"type": "image", "data": base64.b64encode(data).decode(), "mimeType": "image/jpeg"}]


def _txt(obj):
    return [{"type": "text", "text": obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1)}]


def liveview_snapshot(a):
    lv = LiveView(LV_PORT)
    frame = None
    try:
        cam.set_mode("rec", a.get("size", "0640x0480"))
        time.sleep(1)
        lv.start()
        cam.start_liveview(LV_PORT)
        seq, t = 0, time.time()
        n = 0
        while time.time() - t < 4:
            seq, f = lv.wait_frame(seq, 1.0)
            if f:
                n += 1
                frame = f
                if n >= 40:  # let the exposure settle
                    break
    finally:
        try:
            cam.stop_liveview()
        except CameraError:
            pass
        lv.stop()
    return _img(frame) if frame else _txt("Kein Frame empfangen")


def download(a):
    os.makedirs(CAPTURES, exist_ok=True)
    dest = os.path.join(CAPTURES, os.path.basename(a["path"]))
    if os.path.exists(dest):
        return _txt("Existiert schon: " + dest)
    cam.fetch_file(a["path"], dest)
    return _txt("Gespeichert: " + dest)


def list_images(a):
    imgs = cam.images(a.get("dir", "/DCIM"))
    imgs.sort(key=lambda e: (e["date"], e["time"]), reverse=True)
    n = int(a.get("limit", 20))
    return _txt([{"path": i["path"], "size": i["size"]} for i in imgs[:n]])


def props(a):
    p = cam.props()
    if a.get("name"):
        p = {a["name"]: p[a["name"]]}
    return _txt({k: {"value": v["value"], "writable": v["writable"],
                     "enum": v["enum"] if a.get("name") else None} for k, v in p.items()})


def S(**props_):
    return {"type": "object", "properties": props_, "additionalProperties": False}


STR = {"type": "string"}
TOOLS = {
    "camera_status": ("Modell und Befehlsliste der Kamera (lesend).", S(), True,
                      lambda a: _txt({"model": cam.caminfo(), "cgis": sorted(cam.commandlist()),
                                      "allow_write": cam.allow_write})),
    "camera_props": ("Kameraeinstellungen lesen; mit name auch die erlaubten Werte (lesend).",
                     S(name=STR), True, props),
    "list_images": ("Neueste Dateien auf der Karte (lesend).",
                    S(dir=STR, limit={"type": "integer"}), True, list_images),
    "get_thumbnail": ("Vorschaubild einer Datei, Pfad z. B. /DCIM/111OLYMP/_B072121.JPG (lesend).",
                      {"type": "object", "properties": {"path": STR}, "required": ["path"]}, True,
                      lambda a: _img(cam.thumbnail(a["path"]))),
    "download_image": ("Datei von der Karte nach captures/ speichern, überschreibt nichts (lesend auf der Kamera).",
                       {"type": "object", "properties": {"path": STR}, "required": ["path"]}, True, download),
    "liveview_snapshot": ("Schaltet die Kamera in den Aufnahmemodus, holt ein Liveview-Bild und stoppt. "
                          "Ändert den Kamerazustand.", S(size=STR), False, liveview_snapshot),
    "set_property": ("Eine Kameraeinstellung setzen, z. B. prop=expcomp value=+0.3. Schreibend.",
                     {"type": "object", "properties": {"prop": STR, "value": STR},
                      "required": ["prop", "value"]}, False,
                     lambda a: (cam.set_prop(a["prop"], a["value"]), _txt("gesetzt"))[1]),
    "shoot": ("Einmal auslösen. Schreibt ein Foto auf die Karte.", S(), False,
              lambda a: (cam.shoot(), _txt("ausgelöst"))[1]),
}


def handle(msg):
    m, mid, p = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if m == "initialize":
        return {"protocolVersion": p.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}}, "serverInfo": {"name": "omcap", "version": "0.1"}}
    if m == "ping":
        return {}
    if m == "tools/list":
        return {"tools": [{"name": n, "description": d, "inputSchema": s,
                           "annotations": {"readOnlyHint": ro, "destructiveHint": not ro}}
                          for n, (d, s, ro, _) in TOOLS.items()]}
    if m == "tools/call":
        try:
            content = TOOLS[p["name"]][3](p.get("arguments") or {})
            return {"content": content}
        except (CameraError, WriteBlocked, KeyError) as e:
            return {"content": _txt("Fehler: %s" % e), "isError": True}
    if mid is None:
        return None  # Notification
    raise LookupError(m)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        try:
            res = handle(msg)
            out = None if res is None else {"jsonrpc": "2.0", "id": msg["id"], "result": res}
        except LookupError as e:
            out = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "Unbekannt: %s" % e}}
        if out:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

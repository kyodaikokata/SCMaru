"""Read-only localhost browser source, independent of the operator window."""
import json
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
import fonts

PAGE = (Path(__file__).parent / 'assets/overlay.html').read_bytes()
REVISION = hashlib.sha256(PAGE + fonts.css().encode('utf-8')).hexdigest()[:12]
PAGE = PAGE.replace(b'__SCMARU_REVISION__', REVISION.encode('ascii'))

EFFECTS = dict(weight=600, shadow_enabled=True, shadow_offset=2, shadow_blur=4,
               shadow_opacity=.65, shadow_color='#000000', glow_enabled=False,
               glow_blur=8, glow_opacity=.7, glow_color='#e4b6cd',stroke_enabled=False,stroke_width=1.5,stroke_color='#000000',italic_enabled=False,bold_enabled=False)


def normalize_effects(values):
    result = dict(EFFECTS)
    for name, (low, high) in dict(weight=(100,900), shadow_offset=(-30,30), shadow_blur=(0,60),
                                 shadow_opacity=(0,1), glow_blur=(0,80), glow_opacity=(0,1),stroke_width=(0,12)).items():
        try: result[name] = max(low, min(high, float(values.get(name, result[name]))))
        except (ValueError, TypeError): pass
    for name in ('shadow_enabled', 'glow_enabled','stroke_enabled','italic_enabled','bold_enabled'): result[name] = bool(values.get(name, result[name]))
    if 'bold_enabled' not in values: result['bold_enabled']=result['weight']>=700
    import re
    for name in ('shadow_color', 'glow_color','stroke_color'):
        color = values.get(name, result[name])
        if isinstance(color, str) and re.fullmatch('#[0-9a-fA-F]{6}', color): result[name] = color
    return result


class Overlay:
    def __init__(self, port=18964):
        self.lock = threading.Lock()
        self.state = dict(text="", connected=False, offline="SCMaru offline", revision=REVISION)
        owner = self
        font_files = {entry['file']: fonts.ROOT / entry['file'] for entry in fonts.entries()}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = unquote(urlsplit(self.path).path)
                if path == "/state":
                    with owner.lock:
                        body = json.dumps(owner.state, ensure_ascii=False).encode("utf-8")
                    content_type = "application/json; charset=utf-8"
                elif path in ("/", "/overlay", '/preview'):
                    body, content_type = PAGE, "text/html; charset=utf-8"
                elif path == '/fonts.css':
                    body, content_type = fonts.css().encode('utf-8'), 'text/css; charset=utf-8'
                elif path.startswith('/fonts/') and path[7:] in font_files:
                    body, content_type = font_files[path[7:]].read_bytes(), 'font/ttf'
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def update(self, text, connected, offline, size=36, color='#ffffff', font='sans-serif', **effects):
        with self.lock:
            self.state = dict(text=text, connected=connected, offline=offline, size=size, color=color, font=font, revision=REVISION,
                              **normalize_effects(effects))

    def url(self, path='overlay'):
        return f'http://127.0.0.1:{self.port}/{path}?v={REVISION}'

    def close(self):
        self.server.shutdown()
        self.server.server_close()

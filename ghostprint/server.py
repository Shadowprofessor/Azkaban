import hmac
import json
from secrets import token_urlsafe
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .cases import BY_CASE
from .model import rank
from .speech import Speech
from .voice import LocalVoice
from .web_activity import WebActivity, answer, hostname


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; connect-src 'self'; media-src blob:; "
                         "script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, data):
        self.send(status, "application/json; charset=utf-8", json.dumps(data).encode())


def dashboard(report, port, voice_model=None):
    static = Path(__file__).with_name("static")
    activity = WebActivity()
    voice = LocalVoice(voice_model)
    speech = Speech()
    pairing_code = token_urlsafe(24)
    assets = {route: (static / name, mime) for route, name, mime in [
        ("/", "index.html", "text/html"),
        ("/app.js", "app.js", "text/javascript"),
        ("/live.js", "live.js", "text/javascript"),
        ("/style.css", "style.css", "text/css"),
    ]}

    class Dashboard(Handler):
        def valid_host(self):
            address = self.server.server_port
            return self.headers.get("Host") in {f"127.0.0.1:{address}", f"localhost:{address}"}

        def do_GET(self):
            if not self.valid_host():
                self.send_json(403, {"error": "Use the local dashboard URL."})
            elif self.path == "/api/report":
                self.send_json(200, report)
            elif self.path == "/api/live":
                self.send_json(200, {"sites": activity.snapshot()})
            elif self.path == "/api/live/settings":
                self.send_json(200, {"pairing_code": pairing_code, "voice": voice.enabled,
                                     "read_languages": speech.languages(), "dictation_languages": voice.languages})
            elif self.path in assets:
                path, mime = assets[self.path]
                self.send(200, f"{mime}; charset=utf-8", path.read_bytes())
            else:
                self.send_json(404, {"error": "Unknown route."})

        def read_body(self, maximum):
            self.connection.settimeout(6)
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= maximum:
                raise ValueError("Request size is outside the supported limit.")
            data = self.rfile.read(length)
            if len(data) != length:
                raise ValueError("Request body was incomplete.")
            return data

        def do_POST(self):
            if not self.valid_host():
                self.send_json(403, {"error": "Use the local dashboard URL."})
                return
            origin = self.headers.get("Origin")
            if self.path == "/api/live/event":
                authorization = self.headers.get("Authorization", "").encode()
                if not hmac.compare_digest(authorization, f"Bearer {pairing_code}".encode()):
                    self.send_json(401, {"error": "Pair the extension with this dashboard."})
                    return
            elif origin != f"http://{self.headers.get('Host')}":
                self.send_json(403, {"error": "Use the local dashboard to submit this request."})
                return
            try:
                if self.path == "/api/live/event":
                    body = json.loads(self.read_body(4096))
                    if not isinstance(body, dict) or set(body) - {"site", "links"} or "site" not in body:
                        raise ValueError("Expected a website hostname and optional public links.")
                    activity.add(body["site"], body.get("links"))
                    self.send_json(200, {"recorded": True})
                elif self.path == "/api/live/clear":
                    activity.clear()
                    self.send_json(200, {"cleared": True})
                elif self.path == "/api/live/ask":
                    body = json.loads(self.read_body(8192))
                    prompt = body.get("prompt") if isinstance(body, dict) else None
                    if not isinstance(prompt, str) or len(prompt) > 1500:
                        raise ValueError("Enter a prompt of up to 1,500 characters.")
                    site = hostname(body["site"]) if body.get("site") else ""
                    self.send_json(200, answer(prompt, site, activity.links(site)))
                elif self.path == "/api/voice":
                    if self.headers.get_content_type() not in {"audio/webm", "audio/ogg", "audio/mp4", "audio/wav"}:
                        raise ValueError("Unsupported recording format.")
                    audio = self.read_body(3 * 1024 * 1024)
                    language = self.headers.get("X-GhostPrint-Language") or None
                    try:
                        result = voice.transcribe(audio, language)
                    except RuntimeError as error:
                        self.send_json(503, {"error": str(error)})
                    except Exception:
                        self.send_json(422, {"error": "Could not decode the recording or load the local model."})
                    else:
                        self.send_json(200, result)
                elif self.path == "/api/read":
                    body = json.loads(self.read_body(12_288))
                    prompt = body.get("prompt") if isinstance(body, dict) else None
                    language = body.get("language") if isinstance(body, dict) else None
                    if (not isinstance(prompt, str) or not 0 < len(prompt.strip()) <= 1500
                            or "\x00" in prompt or not isinstance(language, str)):
                        raise ValueError("Enter a prompt and choose a voice.")
                    self.send(200, "audio/wav", speech.render(prompt, language))
                else:
                    self.send_json(404, {"error": "Unknown route."})
            except (ValueError, TimeoutError) as error:
                self.send_json(400, {"error": str(error)})

    run(Dashboard, "127.0.0.1", port)


def bridge(host, port, token, *, base, model):
    class ModelBridge(Handler):
        def do_POST(self):
            if self.path != "/v1/benchmark":
                self.send_json(404, {"error": "Unknown route."})
                return
            header = self.headers.get("Authorization", "").encode()
            if token and not hmac.compare_digest(header, f"Bearer {token}".encode()):
                self.send_json(401, {"error": "Unauthorized."})
                return
            try:
                self.connection.settimeout(5)
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 128:
                    raise ValueError()
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict) or set(body) != {"case"} or not isinstance(body["case"], str):
                    raise ValueError()
                if body["case"] not in BY_CASE:
                    raise ValueError()
            except (ValueError, TimeoutError):
                self.send_json(400, {"error": "Expected a built-in synthetic case ID."})
                return
            try:
                result = rank(body["case"], base=base, model=model)
            except RuntimeError as error:
                self.send_json(502, {"error": str(error)})
            else:
                self.send_json(200, result)

    run(ModelBridge, host, port)


def run(handler, host, port):
    with ThreadingHTTPServer((host, port), handler) as server:
        print(f"Listening on http://{host}:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass

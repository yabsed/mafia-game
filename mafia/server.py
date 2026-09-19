"""Loopback-only HTTP UI and a single, serialized game worker."""
from __future__ import annotations

import argparse
import copy
import hmac
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import engine, provider
from .storage import BudgetExceeded, Store, money

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path) -> None:
    """Small .env reader, NOT a shell; environment variables take precedence."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (x.strip() for x in line.split("=", 1))
        if key in {"DEEPSEEK_API_KEY", "TOTAL_BUDGET_USD", "MAFIA_DATA_DIR"}:
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key, value)


class App:
    def __init__(self, store: Store, key: str = ""):
        self.store, self.key = store, key
        self.token = secrets.token_urlsafe(32)
        self.cv = threading.Condition(threading.RLock())
        self.game = store.load()
        self.playing = self.busy = self.step_requested = self.closed = False
        self.delay = 2.4
        self.error = ""
        self.ready_at = 0.0
        self.worker = threading.Thread(target=self.work, daemon=True, name="village-worker")
        self.worker.start()

    def state(self, reveal: bool = False) -> dict:
        with self.cv:
            g = engine.spectator(self.game, reveal) if self.game else None
            return dict(game=g, playing=self.playing, busy=self.busy, error=self.error,
                        delay=self.delay, ledger=self.store.summary(g["id"] if g else None))

    def command(self, path: str, data: dict):
        with self.cv:
            if path == "/api/new":
                if self.busy:
                    raise ValueError("현재 요청이 끝난 뒤 새 마을을 열어 주세요.")
                mode = data.get("mode", "demo")
                if mode == "deepseek" and (not self.key or data.get("consent") is not True):
                    raise ValueError("API 키 설정과 실제 API 과금 동의가 필요합니다.")
                model = data.get("model", "deepseek-flash")
                if not isinstance(model, str) or model not in provider.RATES:
                    raise ValueError("지원하지 않는 모델입니다.")
                cap = money(data.get("budget", "0.15"))
                if not money("0.001") <= cap <= self.store.total:
                    raise ValueError("한 판 예산은 $0.001 이상, 전체 예산 이하여야 합니다.")
                self.game = engine.new_game(count=data.get("count", 7), seed=data.get("seed", 42),
                    rounds=data.get("rounds", 2), mode=mode, model=model, budget=str(cap),
                    max_days=data.get("max_days", 8))
                self.store.save(self.game)
                self.playing = data.get("autoplay") is True
                self.step_requested = False
                self.error = ""
                self.ready_at = time.monotonic() + self.delay
            elif path == "/api/load":
                if self.busy:
                    raise ValueError("현재 요청이 끝난 뒤 기록을 여세요.")
                gid = data.get("id")
                if not isinstance(gid, str) or len(gid) != 32:
                    raise ValueError("올바르지 않은 기록 ID입니다.")
                g = self.store.load(gid)
                if not g:
                    raise ValueError("기록을 찾을 수 없습니다.")
                self.game, self.playing, self.step_requested, self.error = g, False, False, ""
            elif path == "/api/control":
                action = data.get("action")
                if action == "pause":
                    self.playing = self.step_requested = False
                elif action in ("play", "step"):
                    if not self.game or self.game["winner"]:
                        raise ValueError("먼저 새 마을을 열어 주세요.")
                    if self.busy and action == "step":
                        raise ValueError("이미 한 차례가 진행 중입니다.")
                    self.error = ""
                    self.playing = action == "play"
                    self.step_requested = action == "step"
                    self.ready_at = 0
                elif action == "speed":
                    value = data.get("delay")
                    if type(value) not in (int, float) or value not in (0.3, 1.2, 2.4, 4.0):
                        raise ValueError("지원하지 않는 재생 속도입니다.")
                    self.delay = float(value)
                else:
                    raise ValueError("지원하지 않는 조작입니다.")
            else:
                raise ValueError("지원하지 않는 요청입니다.")
            self.cv.notify_all()

    def work(self):
        while True:
            with self.cv:
                while not self.closed:
                    active = self.game and not self.game["winner"] and (self.playing or self.step_requested)
                    wait = self.ready_at - time.monotonic()
                    if active and (self.step_requested or wait <= 0):
                        break
                    self.cv.wait(timeout=max(0.05, min(wait, 0.5)) if active else None)
                if self.closed:
                    return
                self.busy = True
                self.step_requested = False
                game = copy.deepcopy(self.game)
                task = engine.next_task(game)
                view = engine.view_for(game, task)
            try:
                decision = (provider.demo(view, game["seed"], game["turn"]) if game["mode"] == "demo"
                            else provider.deepseek(view, game, task, self.store, self.key))
                # Apply to a copy and persist before publishing: failed writes cannot half-mutate UI state.
                engine.apply(game, task, decision)
                self.store.save(game)
                with self.cv:
                    self.game = game
                    if game["winner"]:
                        self.playing = False
                    # Network uncertainty or malformed output needs an explicit user resume.
                    if decision.get("warning"):
                        self.playing = False
                        self.error = decision["warning"]
            except (BudgetExceeded, provider.ProviderError) as exc:
                with self.cv:
                    self.error = str(exc)
                    self.playing = False
            except Exception:
                # No request bodies, model text, paths, or API keys go into a browser error.
                with self.cv:
                    self.error = "처리를 저장하지 못해 일시정지했습니다. 저장 공간과 서버 상태를 확인하세요."
                    self.playing = False
            finally:
                with self.cv:
                    self.busy = False
                    self.ready_at = time.monotonic() + self.delay
                    self.cv.notify_all()

    def close(self):
        with self.cv:
            self.closed = True
            self.playing = self.step_requested = False
            self.cv.notify_all()
        self.worker.join(timeout=50)
        # A pending reservation survives an interrupted HTTP request.
        if not self.worker.is_alive():
            self.store.close()


def handler_for(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CozyVillage/1.0"

        def log_message(self, fmt, *args):
            pass

        def safe_origin(self) -> bool:
            port = self.server.server_port
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in hosts:
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{h}" for h in hosts}:
                return False
            return self.headers.get("Sec-Fetch-Site") != "cross-site"

        def reply(self, value, status=200, content_type="application/json; charset=utf-8", filename=None):
            raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if not self.safe_origin():
                return self.reply({"error": "로컬 동일 출처 요청만 허용됩니다."}, 403)
            url = urlsplit(self.path)
            reveal = parse_qs(url.query).get("reveal") == ["1"]
            if url.path == "/api/config":
                return self.reply(dict(token=app.token, key_configured=bool(app.key),
                    models={k: dict(input=v[0], cached=v[1], output=v[2]) for k, v in provider.RATES.items()},
                    total_budget=str(app.store.total), prices_checked="2026-09-19"))
            if url.path == "/api/state":
                return self.reply(app.state(reveal))
            if url.path == "/api/history":
                return self.reply(app.store.history())
            if url.path == "/api/export":
                state = app.state(reveal)
                if not state["game"]:
                    return self.reply({"error": "저장할 게임이 없습니다."}, 404)
                return self.reply(dict(format="cozy-mafia-v1", **state),
                                  filename=f'village-{state["game"]["id"][:8]}.json')
            static = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8"),
                      "/favicon.svg": ("favicon.svg", "image/svg+xml")}
            if url.path not in static:
                return self.reply({"error": "찾을 수 없습니다."}, 404)
            name, kind = static[url.path]
            return self.reply((ROOT / "web" / name).read_bytes(), content_type=kind)

        def do_POST(self):
            if not self.safe_origin() or not hmac.compare_digest(self.headers.get("X-Session-Token", ""), app.token):
                return self.reply({"error": "요청 인증에 실패했습니다. 페이지를 새로고침하세요."}, 403)
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.reply({"error": "JSON 요청만 허용됩니다."}, 415)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4096:
                    return self.reply({"error": "요청 크기 제한입니다."}, 413)
                self.connection.settimeout(5)
                def reject_constant(_):
                    raise ValueError("유효하지 않은 숫자입니다.")
                data = json.loads(self.rfile.read(size), parse_constant=reject_constant)
                if not isinstance(data, dict):
                    raise ValueError("JSON 객체가 필요합니다.")
                app.command(urlsplit(self.path).path, data)
                self.reply({"ok": True})
            except (ValueError, TypeError, TimeoutError) as exc:
                self.reply({"error": str(exc)[:240]}, 400)
            except Exception:
                self.reply({"error": "요청을 처리하지 못했습니다."}, 500)
    return Handler


def main():
    parser = argparse.ArgumentParser(description="나는 AI가 아니야! — 로컬 관전 마을")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be 1024–65535")
    load_env(ROOT / ".env")
    data = Path(os.environ.get("MAFIA_DATA_DIR", str(ROOT / "data"))).expanduser()
    data.mkdir(parents=True, exist_ok=True)
    # Fedora/Linux: prevent two workers using the same ledger through different ports.
    import fcntl
    lockfile = (data / "server.lock").open("w")
    try:
        fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.exit(1, "같은 data 폴더를 사용하는 서버가 이미 실행 중입니다.\n")
    os.chmod(data, 0o700)
    app = App(Store(data / "village.sqlite3", os.environ.get("TOTAL_BUDGET_USD", "8.00")),
              os.environ.get("DEEPSEEK_API_KEY", "").strip())
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(app))
        print(f"\n  나는 AI가 아니야!\n  http://127.0.0.1:{args.port}\n  Ctrl+C로 종료 · API 키는 브라우저로 전송되지 않습니다.\n", flush=True)
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\n마을을 저장하고 종료합니다.", flush=True)
    finally:
        app.close()
        if "server" in locals():
            server.server_close()
        lockfile.close()


if __name__ == "__main__":
    main()

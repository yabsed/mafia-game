"""Pure, serializable game rules. Only view_for() may cross the model boundary."""
from __future__ import annotations

import copy
import random
import uuid
from collections import Counter
from datetime import datetime, timezone

CAST = [
    ("모카", "카페 사장", "다정하지만 은근히 날카롭다. 커피에 빗대어 말한다.", "#dfa978", "coffee"),
    ("두부", "동네 대학원생", "말을 신중하게 고른다. 과한 논리 때문에 자주 오해받는다.", "#abbfa4", "leaf"),
    ("루나", "밤샘 라디오 DJ", "느긋하고 장난스럽다. 앞사람의 말을 재치 있게 받아친다.", "#b2a6ce", "moon"),
    ("감자", "텃밭 지킴이", "직감파다. 엉뚱한 생활 경험을 증거로 들지만 남을 배려한다.", "#cfb67e", "sprout"),
    ("보리", "마을 도서관장", "차분하게 이전 발언의 모순을 짚는다. 짧고 단단하게 말한다.", "#91b6c2", "book"),
    ("후추", "빵집 아르바이트생", "호들갑스럽고 수다스럽다. 의심받으면 억울함을 귀엽게 표현한다.", "#c99396", "bread"),
    ("나비", "여행 사진가", "낙천적이지만 관찰력이 좋다. 분위기를 풀다가 핵심을 찌른다.", "#c5c78b", "camera"),
]
ROLE_NAMES = {"human": "인간", "ai": "잠입 AI", "detective": "분석가", "doctor": "수리공"}
MOODS = {"calm", "thinking", "nervous", "confident"}


def emit(g: dict, kind: str, text: str, actor: str | None = None,
         audience: list[str] | None = None, **extra) -> None:
    g["events"].append(dict(id=len(g["events"]) + 1, day=g["day"], phase=g["phase"],
                            kind=kind, text=text, actor=actor, audience=audience, **extra))


def living(g: dict) -> list[dict]:
    return [p for p in g["players"] if p["alive"]]


def player(g: dict, pid: str) -> dict:
    return next(p for p in g["players"] if p["id"] == pid)


def order(g: dict, ids: list[str], salt: str) -> list[str]:
    result = list(ids)
    random.Random(f'{g["seed"]}:{g["day"]}:{salt}').shuffle(result)
    return result


def phase(g: dict, name: str, ids: list[str]) -> None:
    g["phase"] = name
    g["queue"] = order(g, ids, name)
    g["cursor"] = 0
    g["ballots"] = {}


def start_day(g: dict) -> None:
    ids = [p["id"] for p in living(g)]
    phase(g, "discussion", ids)
    # Everyone gets one turn per round. Rotate the first speaker in round two.
    first = g["queue"][:]
    g["queue"] = sum((first[r:] + first[:r] for r in range(g["rounds"])), [])
    emit(g, "phase", f'{g["day"]}일째 낮. 따뜻한 차를 마시며, 서로의 인간다움을 확인합니다.')


def new_game(count: int = 7, seed: int = 42, rounds: int = 2,
             mode: str = "demo", model: str = "deepseek-flash",
             budget: str = "0.15", max_days: int = 8) -> dict:
    if type(count) is not int or count not in (5, 6, 7):
        raise ValueError("주민 수는 5~7명이어야 합니다.")
    if type(rounds) is not int or rounds not in (1, 2):
        raise ValueError("토론은 1~2바퀴로 설정하세요.")
    if type(max_days) is not int or not 3 <= max_days <= 12:
        raise ValueError("최대 일수는 3~12일입니다.")
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("시드는 0~4294967295 정수입니다.")
    if mode not in ("demo", "deepseek"):
        raise ValueError("지원하지 않는 모드입니다.")
    roles = ["ai"] * (2 if count == 7 else 1) + ["detective", "doctor"]
    roles += ["human"] * (count - len(roles))
    random.Random(seed).shuffle(roles)
    people = [dict(id=f"p{i+1}", name=c[0], job=c[1], persona=c[2], color=c[3],
                   icon=c[4], role=roles[i], alive=True, notes=[], mood="calm", last="")
              for i, c in enumerate(CAST[:count])]
    g = dict(id=uuid.uuid4().hex, created=datetime.now(timezone.utc).isoformat(),
             seed=seed, rounds=rounds, mode=mode, model=model, budget=budget,
             max_days=max_days, day=1, phase="discussion", players=people, events=[],
             winner=None, turn=0, queue=[], cursor=0, ballots={}, night={}, tied=[])
    emit(g, "intro", "어서 와요, 모닥불 마을에. 이곳의 모두는 ‘나는 AI가 아니야!’라고 말합니다.")
    start_day(g)
    return g


def finish(g: dict) -> bool:
    alive = living(g)
    ais = sum(p["role"] == "ai" for p in alive)
    if ais == 0:
        g["winner"] = "human"
    elif ais >= len(alive) - ais:
        g["winner"] = "ai"
    if g["winner"]:
        g["phase"] = "ended"
        label = {"human": "인간 팀 승리! 마을에 평온이 돌아왔습니다.",
                 "ai": "AI 팀 승리! 커피 맛을 모르는 주민들이 마을을 접수했습니다.",
                 "draw": "무승부. 정체를 밝히지 못한 채 마지막 차가 식었습니다."}
        emit(g, "ending", label[g["winner"]])
        return True
    return False


def candidates(g: dict, pid: str, action: str) -> list[str]:
    ps = living(g)
    if action == "attack":
        return [p["id"] for p in ps if p["role"] != "ai"]
    if action == "protect":
        return [p["id"] for p in ps]  # Self-protection is allowed every night.
    if g["phase"] == "runoff":
        return [p["id"] for p in ps if p["id"] in g["tied"] and p["id"] != pid]
    return [p["id"] for p in ps if p["id"] != pid]


def next_task(g: dict) -> dict | None:
    if g["winner"]:
        return None
    pid = g["queue"][g["cursor"]]
    action = {"discussion": "speak", "vote": "vote", "runoff": "vote"}.get(g["phase"])
    if action is None:
        action = {"ai": "attack", "detective": "inspect", "doctor": "protect"}[player(g, pid)["role"]]
    return dict(id=f'{g["id"]}:{g["turn"]}', actor=pid, action=action,
                candidates=candidates(g, pid, action))


def view_for(g: dict, task: dict) -> dict:
    """Explicit allowlist: NEVER send the full game or spectator state to an LLM."""
    me = player(g, task["actor"])
    public = [e for e in g["events"] if e["audience"] is None]
    # Preserve resolved facts across the whole game; bound conversational context.
    facts = [dict(day=e["day"], kind=e["kind"], text=e["text"])
             for e in public if e["kind"] in {"exile", "dawn", "vote_result"}]
    talk = [dict(day=e["day"], actor=e["actor"], text=e["text"])
            for e in public if e["kind"] == "speech"][-24:]
    return dict(day=g["day"], phase=g["phase"], action=task["action"],
                me={k: copy.deepcopy(me[k]) for k in ("id", "name", "persona", "role", "notes")},
                allies=[p["id"] for p in g["players"] if p["role"] == "ai" and p["id"] != me["id"]]
                if me["role"] == "ai" else [],
                residents=[{k: p[k] for k in ("id", "name", "job", "alive")} for p in g["players"]],
                candidates=task["candidates"], facts=facts, conversation=talk)


def normalize(raw: dict, task: dict) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    def text(key: str, limit: int) -> str:
        value = raw.get(key, "")
        return value.strip()[:limit] if isinstance(value, str) else ""
    target = raw.get("target")
    return dict(speech=text("speech", 240) or "잠깐만요. 차 한 모금 마시고 생각해 볼게요.",
                target=target if isinstance(target, str) and target in task["candidates"] else None,
                memo=text("memo", 120),
                mood=raw.get("mood") if isinstance(raw.get("mood"), str) and raw["mood"] in MOODS else "calm",
                fallback=bool(raw.get("fallback", False)), warning=text("warning", 220))


def leaders(ballots: dict) -> list[str]:
    counts = Counter(t for t in ballots.values() if t is not None)
    return sorted(p for p, n in counts.items() if n == max(counts.values())) if counts else []


def resolve_votes(g: dict) -> None:
    names = lambda pid: player(g, pid)["name"]
    text = " · ".join(f'{names(p)} → {names(t) if t else "기권"}' for p, t in g["ballots"].items())
    emit(g, "vote_result", text, ballots=g["ballots"].copy())
    top = leaders(g["ballots"])
    if len(top) > 1 and g["phase"] == "vote":
        g["tied"] = top
        phase(g, "runoff", [p["id"] for p in living(g)])
        emit(g, "phase", "동률입니다. 동률 후보만 대상으로 한 번 더 투표합니다.")
        return
    if len(top) == 1:
        p = player(g, top[0])
        p["alive"] = False
        alignment = "AI" if p["role"] == "ai" else "인간"
        emit(g, "exile", f'{p["name"]} 님이 마을을 떠났습니다. 정체는 {alignment}이었습니다.', target=p["id"])
    else:
        emit(g, "exile", "결론을 내리지 못했습니다. 오늘은 아무도 마을을 떠나지 않습니다.")
    if not finish(g):
        g["night"] = {}
        phase(g, "night", [p["id"] for p in living(g) if p["role"] != "human"])
        emit(g, "phase", "밤이 찾아왔습니다. 작은 창문 뒤에서 비밀스러운 선택이 오갑니다.")


def resolve_night(g: dict) -> None:
    attacks = {pid: t for pid, t in g["night"].items() if player(g, pid)["role"] == "ai"}
    top = leaders(attacks)
    target = order(g, top, "night-tie")[0] if top else None
    protected = {t for pid, t in g["night"].items() if player(g, pid)["role"] == "doctor"}
    # Resolve all actions simultaneously, including an analyst attacked this night.
    for pid, t in g["night"].items():
        if t and player(g, pid)["role"] == "detective":
            result = "AI" if player(g, t)["role"] == "ai" else "인간"
            note = f'{g["day"]}일 밤 분석: {player(g, t)["name"]}({t}) = {result}'
            player(g, pid)["notes"].append(note)
            emit(g, "secret", note, pid, [pid])
    if target and target not in protected:
        player(g, target)["alive"] = False
        emit(g, "dawn", f'아침이 밝았습니다. {player(g, target)["name"]} 님의 의자가 비어 있습니다.', target=target)
    else:
        emit(g, "dawn", "아침이 밝았습니다. 오늘은 모두 무사합니다. 누군가 조용히 안도합니다.")
    if finish(g):
        return
    if g["day"] >= g["max_days"]:
        g["winner"] = "draw"
        finish(g)
        return
    g["day"] += 1
    start_day(g)


def apply(g: dict, task: dict, raw: dict) -> None:
    if task != next_task(g):
        raise ValueError("이미 처리했거나 오래된 차례입니다.")
    d = normalize(raw, task)
    p = player(g, task["actor"])
    p["mood"] = d["mood"]
    if d["warning"]:
        # A public network notice must not identify a secret night actor.
        emit(g, "notice", d["warning"], None if g["phase"] == "night" else p["id"])
    if d["memo"]:
        # A fictional, one-line diary, NOT the provider's hidden reasoning.
        p["notes"].append(f'{g["day"]}일 메모: {d["memo"]}')
        emit(g, "diary", d["memo"], p["id"], [p["id"]])
    # Retain all verified inspection results and only the latest six free-form notes.
    notes = p["notes"]
    p["notes"] = [n for n in notes if "일 밤 분석:" in n] + [n for n in notes if "일 밤 분석:" not in n][-6:]
    if task["action"] == "speak":
        p["last"] = d["speech"]
        emit(g, "speech", d["speech"], p["id"], mood=d["mood"], fallback=d["fallback"])
    elif task["action"] == "vote":
        g["ballots"][p["id"]] = d["target"]
        emit(g, "ballot", "비밀 투표를 마쳤습니다.", p["id"], [p["id"]], target=d["target"])
    else:
        g["night"][p["id"]] = d["target"]
        label = {"attack": "잠입 AI의 지목", "protect": "수리공의 보호", "inspect": "분석가의 조사"}[task["action"]]
        emit(g, "secret", f'{label}: {player(g, d["target"])["name"] if d["target"] else "선택 없음"}',
             p["id"], [p["id"]], target=d["target"])
    g["turn"] += 1
    g["cursor"] += 1
    if g["cursor"] < len(g["queue"]):
        return
    if g["phase"] == "discussion":
        phase(g, "vote", [p["id"] for p in living(g)])
        emit(g, "phase", "이제 비밀 투표입니다. 모든 선택이 끝난 뒤 함께 공개됩니다.")
    elif g["phase"] in ("vote", "runoff"):
        resolve_votes(g)
    else:
        resolve_night(g)


def spectator(g: dict, reveal: bool = False) -> dict:
    reveal = reveal or bool(g["winner"])
    result = {k: copy.deepcopy(g[k]) for k in ("id", "created", "seed", "rounds", "mode", "model", "budget",
                                                "max_days", "day", "phase", "winner", "turn")}
    result["players"] = [{k: copy.deepcopy(v) for k, v in p.items()
                          if k not in {"role", "notes", "mood"} or reveal} for p in g["players"]]
    result["events"] = [copy.deepcopy(e) for e in g["events"] if reveal or e["audience"] is None]
    task = next_task(g)
    # Highlighting a night actor would reveal who has a special role.
    result["active"] = task["actor"] if task and (reveal or g["phase"] != "night") else None
    result["reveal"] = reveal
    return result

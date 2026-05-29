#!/usr/bin/env python3
"""Claude (Anthropic) のステータスページを監視し、新しいインシデント更新を Discord に通知する。

データソース: https://status.claude.com/api/v2/incidents.json (Statuspage 公式 JSON API)
依存: なし(Python 標準ライブラリのみ)

環境変数:
  DISCORD_WEBHOOK_URL  Discord の Webhook URL (必須)
  STATE_FILE           状態ファイルのパス (省略時 state.json)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error

INCIDENTS_URL = "https://status.claude.com/api/v2/incidents.json"
STATUS_PAGE = "https://status.claude.com"
USER_AGENT = "claude-status-discord/1.0 (+https://github.com)"
SEEN_LIMIT = 200  # state に保持する更新 ID の上限(古いものから捨てる)

# インシデントの状態ごとの色 (Discord embed の左帯)
STATUS_COLORS = {
    "investigating": 0xE01E5A,  # 赤
    "identified": 0xEA8600,     # 橙
    "monitoring": 0xF1C40F,     # 黄
    "resolved": 0x2ECC71,       # 緑
    "postmortem": 0x3498DB,     # 青
}
DEFAULT_COLOR = 0x95A5A6

STATUS_LABEL = {
    "investigating": "調査中",
    "identified": "原因特定",
    "monitoring": "経過観察",
    "resolved": "復旧",
    "postmortem": "事後報告",
}

IMPACT_LABEL = {
    "none": "影響なし",
    "minor": "軽微",
    "major": "重大",
    "critical": "致命的",
    "maintenance": "メンテナンス",
}


def http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_state(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"seen": [], "initialized": False}
    data.setdefault("seen", [])
    data.setdefault("initialized", bool(data["seen"]))
    return data


def save_state(path: str, state: dict) -> None:
    # 上限を超えたら古い ID を切り捨てる
    state["seen"] = state["seen"][-SEEN_LIMIT:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def post_discord(webhook: str, embed: dict) -> None:
    payload = json.dumps({"embeds": [embed]}).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        # 2xx 以外は urlopen が例外を投げる
        resp.read()


def build_embed(incident: dict, update: dict) -> dict:
    status = update.get("status", "")
    impact = incident.get("impact", "none")
    components = incident.get("components", []) or []
    comp_names = ", ".join(c.get("name", "") for c in components) or "—"

    body = (update.get("body") or "").strip()
    if len(body) > 1800:
        body = body[:1800] + " …"

    fields = [
        {"name": "状態", "value": STATUS_LABEL.get(status, status or "—"), "inline": True},
        {"name": "影響度", "value": IMPACT_LABEL.get(impact, impact), "inline": True},
        {"name": "対象", "value": comp_names, "inline": False},
    ]

    shortlink = incident.get("shortlink") or STATUS_PAGE
    return {
        "title": incident.get("name", "Claude インシデント"),
        "url": shortlink,
        "description": body or "(更新本文なし)",
        "color": STATUS_COLORS.get(status, DEFAULT_COLOR),
        "fields": fields,
        "footer": {"text": "Claude Status"},
        "timestamp": update.get("created_at"),
    }


def main() -> int:
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        print("ERROR: DISCORD_WEBHOOK_URL が未設定です。", file=sys.stderr)
        return 1

    state_file = os.environ.get("STATE_FILE", "state.json")
    state = load_state(state_file)
    seen = set(state["seen"])

    try:
        data = http_get_json(INCIDENTS_URL)
    except urllib.error.URLError as e:
        print(f"ERROR: ステータス API の取得に失敗: {e}", file=sys.stderr)
        return 1

    incidents = data.get("incidents", []) or []

    # (incident, update) を時系列(古い順)に並べ、未通知のものを抽出
    pending: list[tuple[dict, dict]] = []
    for inc in incidents:
        for upd in inc.get("incident_updates", []) or []:
            uid = upd.get("id")
            if uid and uid not in seen:
                pending.append((inc, upd))
    pending.sort(key=lambda t: t[1].get("created_at") or "")

    # 初回(状態ファイルなし)は既読化のみで通知しない = 過去分の一斉送信防止
    if not state.get("initialized"):
        for _, upd in pending:
            seen.add(upd["id"])
        state["seen"] = list(seen)
        state["initialized"] = True
        save_state(state_file, state)
        print(f"初回実行: 既存の {len(pending)} 件をベースラインとして既読化(通知なし)。")
        return 0

    sent = 0
    for inc, upd in pending:
        embed = build_embed(inc, upd)
        try:
            post_discord(webhook, embed)
        except urllib.error.HTTPError as e:
            print(f"WARN: Discord 投稿失敗 (HTTP {e.code}): {inc.get('name')}", file=sys.stderr)
            # 失敗分は既読にせず次回再送する
            continue
        except urllib.error.URLError as e:
            print(f"WARN: Discord 投稿失敗: {e}", file=sys.stderr)
            continue
        seen.add(upd["id"])
        sent += 1

    state["seen"] = list(seen)
    save_state(state_file, state)
    print(f"完了: {sent} 件を通知 (未通知だった候補 {len(pending)} 件)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

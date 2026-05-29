# Claude Status → Discord 通知

Claude (Anthropic) の公式ステータスページを監視し、インシデントの**発生・途中更新・復旧**を Discord に自動通知します。

- データソース: <https://status.claude.com/api/v2/incidents.json>（Statuspage 公式 JSON API）
- 実行: GitHub Actions の cron（5分ごと）
- 依存: なし（Python 標準ライブラリのみ）

## 仕組み

1. 5分ごとに `incidents.json` を取得する。
2. 各インシデントの更新（`incident_updates`）のうち、まだ通知していないものを Discord Webhook に投稿する。
3. 通知済みの更新 ID を `state.json` に記録し、**変化があった時だけ** リポジトリにコミットして戻す（障害が無い間はコミットされず履歴がクリーン）。
4. **初回実行**は既存のインシデントを「既読」にするだけで通知しません（過去分の一斉送信を防止）。以降の新しい更新のみ通知します。

## セットアップ

### 1. Discord の Webhook を作る
1. 通知したい Discord チャンネルの **設定 → 連携サービス → ウェブフック → 新しいウェブフック**
2. **ウェブフックURLをコピー**

### 2. このリポジトリを GitHub に push
```bash
git init
git add .
git commit -m "init: claude status to discord"
git branch -M main
git remote add origin https://github.com/<あなた>/<リポジトリ名>.git
git push -u origin main
```

### 3. Webhook URL を Secret に登録
GitHub のリポジトリで **Settings → Secrets and variables → Actions → New repository secret**
- Name: `DISCORD_WEBHOOK_URL`
- Secret: コピーした Webhook URL

### 4. 動作確認
**Actions** タブ → `Claude Status → Discord` → **Run workflow** で手動実行。
初回は「ベースライン化（通知なし）」で終わります。以降、新しい障害情報が出ると自動で Discord に届きます。

## ローカルで試す

```bash
# Windows PowerShell
$env:DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/..."
python notify.py
```

## 注意

- GitHub の cron は最短5分間隔で、混雑時は数分〜十数分の遅延やまれにスキップが起こり得ます（数分の遅れを許容する前提）。
- 1回の実行で複数の新規更新があれば、古い順にまとめて投稿します。
- Webhook URL は秘匿情報です。コードに直接書かず必ず Secret で管理してください。

## ファイル構成

```
notify.py                       通知スクリプト本体
state.json                      通知済み更新 ID の状態（自動更新）
.github/workflows/claude-status.yml   GitHub Actions ワークフロー
```

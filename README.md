# Claude Status → Discord 通知

Claude (Anthropic) の公式ステータスページを監視し、インシデントの**発生・途中更新・復旧**を Discord に自動通知します。

- データソース: <https://status.claude.com/api/v2/incidents.json>（Statuspage 公式 JSON API）
- 実行: GitHub Actions の cron（5分ごと）
- 依存: なし（Python 標準ライブラリのみ）

> **English:** Monitors Anthropic's official Claude status page and posts incident updates (new / ongoing / resolved) to Discord automatically, via a GitHub Actions cron. Zero dependencies, idempotent state handling, and a first-run baseline that avoids back-posting old incidents. Easily adapted to **Slack / Teams** or any [Statuspage](https://www.atlassian.com/software/statuspage)-based service.

**この実装が示せること（スキル）**: 外部API連携 / 冪等な状態管理 / GitHub Actions による定期実行（CI/CD）/ 耐障害設計（失敗分は既読にせず再送）。監視対象や通知先を差し替えれば、**任意のサービス監視 → Slack・Teams等への通知bot** に転用できます。

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

## Kubernetes（CronJob）で動かす — 5分間隔を確実に

下の「注意」の通り、GitHub Actions の cron は間引かれて数時間空くことがあります。**確実な5分間隔**が欲しいなら、自前の k8s クラスタ（k3s 等）で **CronJob** として回すのが堅実です。マニフェストは [`k8s/cronjob.yaml`](k8s/cronjob.yaml)。

- **CronJob**（`*/5 * * * *`・`concurrencyPolicy: Forbid`）が `python:3.12-slim` で `notify.py` を実行
- スクリプトは **ConfigMap** からマウント（イメージのビルド不要）
- `state.json` は **PersistentVolume**（`STATE_FILE=/data/state.json`）に保存＝実行をまたいで永続（git にコミットして戻す方式の k8s 版）
- Webhook は **Secret**、非 root 実行・受信ポートなし（外向きの送信のみ）

```bash
# 1) namespace + PVC + CronJob
kubectl apply -f k8s/cronjob.yaml

# 2) スクリプトを ConfigMap として投入（リポジトリの notify.py をそのまま）
kubectl -n claude-status create configmap notify-script --from-file=notify.py

# 3) Discord Webhook を Secret として登録（コミットしない）
kubectl -n claude-status create secret generic discord \
  --from-literal=DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'

# 4) 手動で1回試す（初回はベースライン化＝通知なし）
kubectl -n claude-status create job test --from=cronjob/claude-status
kubectl -n claude-status logs job/test
```

> GitHub Actions と k8s CronJob を**両方**動かすと二重通知になります。どちらか一方に統一するか、別チャンネルの Webhook を使ってください。

## ローカルで試す

```bash
# Windows PowerShell
$env:DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/..."
python notify.py
```

## 注意

- GitHub の cron は最短5分間隔の**設定**ですが、実行はベストエフォートです。実測では平均で2〜3時間に1回程度しか起動せず、間隔が数時間空くことがあります（設定上は `*/5` でも、GitHub 側で高頻度 cron が間引かれるため）。
  - 理由: GitHub の `schedule` イベントは保証されず、高負荷時（特に毎時00分付近）は遅延・スキップされます。`*/5` のような高頻度 cron や、アクティビティの少ない個人リポジトリは特に優先度が下げられます。
  - **5分間隔を確実に守りたい場合**は、外部スケジューラ（cron-job.org / UptimeRobot / Cloud Scheduler 等）から `workflow_dispatch` / `repository_dispatch` を叩く、または監視処理を常時起動の環境で回してください。
- 1回の実行で複数の新規更新があれば、古い順にまとめて投稿します。
- Webhook URL は秘匿情報です。コードに直接書かず必ず Secret で管理してください。

## ファイル構成

```
notify.py                       通知スクリプト本体
state.json                      通知済み更新 ID の状態（自動更新）
.github/workflows/claude-status.yml   GitHub Actions ワークフロー
k8s/cronjob.yaml                Kubernetes CronJob（namespace + PVC + CronJob）
```

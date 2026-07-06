# 新聞爬蟲

Python 爬蟲 + Flask 網頁。使用者在網頁勾選想看的主題，後端即時從各新聞網站抓取並彙整最新新聞。

## 快速開始

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

開啟瀏覽器前往 <http://127.0.0.1:5000>，勾選主題後按「抓取新聞」。

## 支援主題

時事、熱門話題、政治（國內外）、財經（國內外）、天氣、體育（棒球，優先顯示棒球新聞）、社會、3C。

## 資料來源與抓取方式

| 來源 | 方式 |
|---|---|
| 自由時報 | 官方 RSS（all / politics / world / business / sports / society / life / novelty） |
| 聯合新聞網 | 即時新聞 JSON API（官方 RSS 內容已清空，故改用 `udn.com/api/more`） |
| 報導者 | 官方 RSS（`public.twreporter.org`） |
| ETtoday | 即時新聞列表與熱門新聞頁 HTML 解析 |
| Yahoo新聞 | 官方分類 RSS |
| 天下雜誌 | 首頁 HTML 解析（該站以 WAF 阻擋自動化流量，失敗時 UI 會顯示來源異常提示） |

依 CLAUDE.md 規定，**不使用**頂五（basketballtop5.com）。

## 設計說明

- 各來源以 ThreadPoolExecutor 並行抓取，單一來源失敗不影響其他來源。
- 來源頁面有 5 分鐘快取，避免頻繁請求對方網站。
- 主題相關性把關：
  - 「天氣」以關鍵字（颱風、鋒面、高溫…）從生活/即時新聞中過濾。
  - 「體育（棒球）」只顯示符合棒球關鍵字（中職、MLB、日職、球隊名…）的新聞。
  - 「熱門話題」取自各站真正的熱門排行（ETtoday 熱門新聞、自由時報熱門排行 API）。
  - 部分來源的分類 feed 會混入無關新聞（如 Yahoo 政治 feed 夾帶社會新聞），
    這類 feed 另以政治關鍵字二次過濾，確保顯示內容與勾選主題一致。
- 結果依來源輪流排列，避免單一來源洗版；同標題/同網址自動去重。

## API

`GET /api/news?topics=politics,sports&per_topic=10`

- `topics`：逗號分隔的主題 key（current / hot / politics / finance / weather / sports / society / tech）
- `per_topic`：每主題筆數（1–10，預設 10）

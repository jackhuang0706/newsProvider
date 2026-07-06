# -*- coding: utf-8 -*-
"""新聞爬蟲網頁伺服器：提供主題勾選 UI 與新聞彙整 API。"""
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

import scraper

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False


@app.get("/")
def index():
    return render_template("index.html", topics=scraper.TOPICS)


@app.get("/favicon.svg")
def favicon():
    return send_from_directory(Path(app.root_path), "favicon.svg", mimetype="image/svg+xml")


@app.get("/api/news")
def api_news():
    topics = [t for t in request.args.get("topics", "").split(",") if t in scraper.TOPICS]
    if not topics:
        return jsonify({"error": "請至少勾選一個主題"}), 400
    try:
        per_topic = int(request.args.get("per_topic", 10))
    except ValueError:
        per_topic = 10
    per_topic = max(1, min(per_topic, 10))
    return jsonify(scraper.fetch_news(topics, per_topic))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

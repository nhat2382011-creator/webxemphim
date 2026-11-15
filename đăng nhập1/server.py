#!/usr/bin/env python3
"""
CineVault Server - Máy chủ giữ kho link phim (movies.db) và phục vụ:
- Trang người xem: / , /index.html , /cinevault.html (ưu tiên cinevault-v3.html -> cinevault.html -> index.html)
- Trang QTDL:      /qtdl.html
- API dữ liệu:     /api/movies (GET, POST), /api/movies/import (POST), /api/movies/<id> (DELETE)

Chạy:   python server-v2.py          (mặc định cổng 8000)
        python server-v2.py 8080     (cổng tùy chọn)
Mở:     http://localhost:8000
"""
import json
import os
import sqlite3
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "movies.db")
MAX_BODY = 50_000


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS movies(
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            genre TEXT NOT NULL DEFAULT 'Khác',
            year TEXT DEFAULT '',
            poster TEXT DEFAULT '',
            note TEXT DEFAULT '',
            fav INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        )
        """)


def find_html_file(candidates):
    for name in candidates:
        p = os.path.join(BASE, name)
        if os.path.isfile(p):
            return p
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "CineVaultServer/2.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, candidates, missing_msg):
        html_path = find_html_file(candidates)
        if not html_path:
            return self.send_json(404, {"error": missing_msg})
        with open(html_path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY:
            return None
        try:
            data = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path in ("/", "/index.html", "/cinevault.html", "/cinevault-v3.html"):
            return self.send_html(
                ("cinevault-v3.html", "cinevault.html", "index.html"),
                "Không tìm thấy cinevault-v3.html / cinevault.html / index.html cùng thư mục với server-v2.py.",
            )

        if path == "/qtdl.html":
            return self.send_html(
                ("qtdl.html",),
                "Không tìm thấy qtdl.html cùng thư mục với server-v2.py.",
            )

        if path == "/api/movies":
            with db() as c:
                rows = c.execute(
                    "SELECT id, title, url, genre, year, poster, note, fav, created_at "
                    "FROM movies ORDER BY created_at DESC"
                ).fetchall()
            movies = []
            for r in rows:
                item = dict(r)
                item["fav"] = bool(item["fav"])
                movies.append(item)
            return self.send_json(200, {"movies": movies})

        return self.send_json(404, {"error": "Không tìm thấy đường dẫn."})

    def do_POST(self):
        path = self.path.split("?", 1)[0]

        if path == "/api/movies":
            data = self.read_json()
            if not data:
                return self.send_json(400, {"error": "Dữ liệu không hợp lệ."})
            title = str(data.get("title", "")).strip()
            url = str(data.get("url", "")).strip()
            if not title or not url:
                return self.send_json(400, {"error": "Cần nhập tên phim và link phim."})
            movie_id = str(data.get("id") or f"m-{int(time.time() * 1000)}")
            genre = str(data.get("genre", "Khác")).strip() or "Khác"
            year = str(data.get("year", "")).strip()
            poster = str(data.get("poster", "")).strip()
            note = str(data.get("note", "")).strip()
            fav = 1 if data.get("fav") else 0
            created_at = int(data.get("created_at") or time.time() * 1000)

            with db() as c:
                c.execute(
                    """
                    INSERT INTO movies(id, title, url, genre, year, poster, note, fav, created_at)
                    VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title,
                        url=excluded.url,
                        genre=excluded.genre,
                        year=excluded.year,
                        poster=excluded.poster,
                        note=excluded.note,
                        fav=excluded.fav
                    """,
                    (movie_id, title, url, genre, year, poster, note, fav, created_at),
                )
            return self.send_json(200, {"ok": True, "id": movie_id})

        if path == "/api/movies/import":
            data = self.read_json()
            if not data or not isinstance(data.get("movies"), list):
                return self.send_json(400, {"error": "Danh sách phim nhập vào không hợp lệ."})
            added = 0
            with db() as c:
                for m in data["movies"]:
                    if not isinstance(m, dict):
                        continue
                    title = str(m.get("title", "")).strip()
                    url = str(m.get("url", "")).strip()
                    if not title or not url:
                        continue
                    mid = str(m.get("id") or f"imp-{int(time.time() * 1000)}-{added}")
                    c.execute(
                        """
                        INSERT INTO movies(id, title, url, genre, year, poster, note, fav, created_at)
                        VALUES(?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(id) DO UPDATE SET
                            title=excluded.title,
                            url=excluded.url,
                            genre=excluded.genre,
                            year=excluded.year,
                            poster=excluded.poster,
                            note=excluded.note,
                            fav=excluded.fav
                        """,
                        (
                            mid,
                            title,
                            url,
                            str(m.get("genre", "Khác")),
                            str(m.get("year", "")),
                            str(m.get("poster", "")),
                            str(m.get("note", "")),
                            1 if m.get("fav") else 0,
                            int(m.get("created_at") or time.time() * 1000),
                        ),
                    )
                    added += 1
            return self.send_json(200, {"ok": True, "count": added})

        return self.send_json(404, {"error": "Không tìm thấy đường dẫn."})

    def do_DELETE(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/movies/"):
            movie_id = path[len("/api/movies/"):].strip()
            if not movie_id:
                return self.send_json(400, {"error": "Thiếu ID phim."})
            with db() as c:
                c.execute("DELETE FROM movies WHERE id = ?", (movie_id,))
            return self.send_json(200, {"ok": True})
        return self.send_json(404, {"error": "Không tìm thấy đường dẫn."})


if __name__ == "__main__":
    init_db()
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8000
    main_html = find_html_file(("cinevault-v3.html", "cinevault.html", "index.html"))
    qtdl_html = find_html_file(("qtdl.html",))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"CineVault Server đang chạy tại http://localhost:{port}")
    print(f"Trang xem:  {main_html or 'CHƯA TÌM THẤY file HTML trang chính'}")
    print(f"Trang QTDL: {qtdl_html or 'CHƯA TÌM THẤY qtdl.html'}")
    print(f"Kho dữ liệu server: {DB_PATH}")
    print("Nhấn Ctrl+C để dừng.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng server.")
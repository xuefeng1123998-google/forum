
from flask import Flask, render_template, request, redirect, url_for, session, g, flash
import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "forum.db"

app = Flask(__name__)
app.secret_key = "dev-secret-change-me"

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'member',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        author_id INTEGER,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(author_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        section TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        is_featured INTEGER NOT NULL DEFAULT 0,
        is_hidden INTEGER NOT NULL DEFAULT 0,
        likes_count INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        body TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        is_hidden INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(post_id) REFERENCES posts(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS likes (
        user_id INTEGER NOT NULL,
        post_id INTEGER NOT NULL,
        PRIMARY KEY(user_id, post_id),
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(post_id) REFERENCES posts(id)
    );
    """)
    db.commit()

    if not c.execute("SELECT 1 FROM users WHERE username='admin'").fetchone():
        c.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            ("admin", generate_password_hash("admin123"), "admin"),
        )
    if not c.execute("SELECT 1 FROM users WHERE username='member1'").fetchone():
        c.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            ("member1", generate_password_hash("member123"), "member"),
        )
    if not c.execute("SELECT 1 FROM announcements").fetchone():
        admin_id = c.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        c.execute("INSERT INTO announcements (title, body, author_id) VALUES (?, ?, ?)",
                  ("四月共读会报名开启", "本月共读书目为《人间词话》。周三晚 19:00 于社团阅览室举行，欢迎在会前发布摘录与疑问。", admin_id))
        c.execute("INSERT INTO announcements (title, body, author_id) VALUES (?, ?, ?)",
                  ("论坛采用后审制度", "成员发帖后将直接展示，管理员会进行例行巡检；不当内容会被下架并通知作者。", admin_id))
    if not c.execute("SELECT 1 FROM posts").fetchone():
        admin_id = c.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        member_id = c.execute("SELECT id FROM users WHERE username='member1'").fetchone()[0]
        c.execute("INSERT INTO posts (title, body, section, user_id, is_featured, likes_count) VALUES (?, ?, ?, ?, ?, ?)",
                  ("读《人间词话》时，我第一次感受到“境界”不是抽象词", "以前总觉得“境界”只是文学评论里的大词，这次重读时才意识到它和一个人的感受方式有关。王国维写得并不远，反而很贴近日常。", "读书感想", member_id, 1, 12))
        c.execute("INSERT INTO posts (title, body, section, user_id, likes_count) VALUES (?, ?, ?, ?, ?)",
                  ("下周活动主持人分工建议，大家看看是否需要补充", "我先列了开场、分组讨论、总结发言三个环节的基本安排。如果有人愿意负责摘录和现场记录，也可以在评论区认领。", "活动交流", admin_id, 5))
        post_id = c.execute("SELECT id FROM posts ORDER BY id LIMIT 1").fetchone()[0]
        c.execute("INSERT INTO comments (post_id, body, user_id) VALUES (?, ?, ?)",
                  (post_id, "你这句“感受方式”说得特别好，我也有类似体验。", admin_id))
    db.commit()
    db.close()

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("user_id") is None:
            flash("请先登录。")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            flash("仅管理员可执行此操作。")
            return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapped

@app.context_processor
def inject_user():
    return {"current_user": {"id": session.get("user_id"), "username": session.get("username"), "role": session.get("role")}}

@app.route("/")
def index():
    db = get_db()
    announcements = db.execute("""
        SELECT a.*, u.username AS author_name
        FROM announcements a LEFT JOIN users u ON a.author_id=u.id
        WHERE a.is_active=1
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT 3
    """).fetchall()
    featured = db.execute("""
        SELECT p.*, u.username
        FROM posts p JOIN users u ON p.user_id=u.id
        WHERE p.is_hidden=0 AND p.is_featured=1
        ORDER BY p.created_at DESC, p.id DESC
        LIMIT 5
    """).fetchall()
    posts = db.execute("""
        SELECT p.*, u.username,
               (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id AND c.is_hidden=0) AS comments_count
        FROM posts p JOIN users u ON p.user_id=u.id
        WHERE p.is_hidden=0
        ORDER BY p.created_at DESC, p.id DESC
    """).fetchall()
    return render_template("index.html", announcements=announcements, featured=featured, posts=posts)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("index"))
        flash("用户名或密码不正确。")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        if len(username) < 3 or len(password) < 6:
            flash("用户名至少 3 位，密码至少 6 位。")
            return render_template("register.html")
        db = get_db()
        try:
            db.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'member')",
                       (username, generate_password_hash(password)))
            db.commit()
            flash("注册成功，请登录。")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("用户名已存在。")
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/post/new", methods=["GET", "POST"])
@login_required
def new_post():
    if request.method == "POST":
        title = request.form["title"].strip()
        section = request.form["section"].strip()
        body = request.form["body"].strip()
        if not title or not body or not section:
            flash("请填写完整内容。")
            return render_template("new_post.html")
        db = get_db()
        db.execute("INSERT INTO posts (title, body, section, user_id) VALUES (?, ?, ?, ?)",
                   (title, body, section, session["user_id"]))
        db.commit()
        flash("发帖成功。")
        return redirect(url_for("index"))
    return render_template("new_post.html")

@app.route("/post/<int:post_id>", methods=["GET", "POST"])
def post_detail(post_id):
    db = get_db()
    post = db.execute("""
        SELECT p.*, u.username
        FROM posts p JOIN users u ON p.user_id=u.id
        WHERE p.id=? AND p.is_hidden=0
    """, (post_id,)).fetchone()
    if not post:
        flash("帖子不存在或已下架。")
        return redirect(url_for("index"))
    if request.method == "POST":
        if session.get("user_id") is None:
            flash("请先登录后再评论。")
            return redirect(url_for("login"))
        body = request.form["body"].strip()
        if body:
            db.execute("INSERT INTO comments (post_id, body, user_id) VALUES (?, ?, ?)",
                       (post_id, body, session["user_id"]))
            db.commit()
            flash("评论已发布。")
        return redirect(url_for("post_detail", post_id=post_id))
    comments = db.execute("""
        SELECT c.*, u.username
        FROM comments c JOIN users u ON c.user_id=u.id
        WHERE c.post_id=? AND c.is_hidden=0
        ORDER BY c.created_at ASC, c.id ASC
    """, (post_id,)).fetchall()
    liked = False
    if session.get("user_id"):
        liked = db.execute("SELECT 1 FROM likes WHERE user_id=? AND post_id=?", (session["user_id"], post_id)).fetchone() is not None
    return render_template("post_detail.html", post=post, comments=comments, liked=liked)

@app.route("/post/<int:post_id>/like", methods=["POST"])
@login_required
def like_post(post_id):
    db = get_db()
    already = db.execute("SELECT 1 FROM likes WHERE user_id=? AND post_id=?", (session["user_id"], post_id)).fetchone()
    if already:
        db.execute("DELETE FROM likes WHERE user_id=? AND post_id=?", (session["user_id"], post_id))
        db.execute("UPDATE posts SET likes_count = CASE WHEN likes_count>0 THEN likes_count-1 ELSE 0 END WHERE id=?", (post_id,))
    else:
        db.execute("INSERT INTO likes (user_id, post_id) VALUES (?, ?)", (session["user_id"], post_id))
        db.execute("UPDATE posts SET likes_count = likes_count + 1 WHERE id=?", (post_id,))
    db.commit()
    return redirect(request.referrer or url_for("index"))

@app.route("/admin")
@login_required
@admin_required
def admin():
    db = get_db()
    posts = db.execute("""
        SELECT p.*, u.username
        FROM posts p JOIN users u ON p.user_id=u.id
        ORDER BY p.created_at DESC, p.id DESC
    """).fetchall()
    announcements = db.execute("""
        SELECT a.*, u.username AS author_name
        FROM announcements a LEFT JOIN users u ON a.author_id=u.id
        ORDER BY a.created_at DESC, a.id DESC
    """).fetchall()
    return render_template("admin.html", posts=posts, announcements=announcements)

@app.route("/admin/announcement/new", methods=["POST"])
@login_required
@admin_required
def new_announcement():
    title = request.form["title"].strip()
    body = request.form["body"].strip()
    if title and body:
        db = get_db()
        db.execute("INSERT INTO announcements (title, body, author_id) VALUES (?, ?, ?)",
                   (title, body, session["user_id"]))
        db.commit()
        flash("公告已发布。")
    return redirect(url_for("admin"))

@app.route("/admin/post/<int:post_id>/feature", methods=["POST"])
@login_required
@admin_required
def toggle_feature(post_id):
    db = get_db()
    db.execute("UPDATE posts SET is_featured = CASE WHEN is_featured=1 THEN 0 ELSE 1 END WHERE id=?", (post_id,))
    db.commit()
    return redirect(url_for("admin"))

@app.route("/admin/post/<int:post_id>/hide", methods=["POST"])
@login_required
@admin_required
def toggle_hide(post_id):
    db = get_db()
    db.execute("UPDATE posts SET is_hidden = CASE WHEN is_hidden=1 THEN 0 ELSE 1 END WHERE id=?", (post_id,))
    db.commit()
    return redirect(url_for("admin"))

if __name__ == "__main__":
    init_db()
    app.run(debug=True)

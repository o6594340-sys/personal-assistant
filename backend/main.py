import os
import json
import sqlite3
from datetime import date, datetime, timedelta
from contextlib import contextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import anthropic

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DB_PATH = os.path.join(os.path.dirname(__file__), "assistant.db")
FRONTEND_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                color TEXT NOT NULL DEFAULT '#6B7280',
                description TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'work',
                date TEXT NOT NULL,
                time_start TEXT,
                completed INTEGER NOT NULL DEFAULT 0,
                project_id INTEGER REFERENCES projects(id),
                is_buffer INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS ideas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                remind_at TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS horizon (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                timeframe TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS quotes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                text TEXT NOT NULL,
                author TEXT NOT NULL
            );
        """)

        # Seed default projects if empty
        count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        if count == 0:
            conn.executemany(
                "INSERT INTO projects (name, color, description) VALUES (?, ?, ?)",
                [
                    ("Match Point", "#3B82F6", "Основной бизнес — representation/B2B туризм"),
                    ("Taylor Studio", "#10B981", "DMC — иностранные туристы + MICE"),
                    ("Боты", "#8B5CF6", "Проект автоматизации — на паузе"),
                    ("Личное", "#F59E0B", "Здоровье, отдых, женственность, ремонт"),
                ],
            )


# ---------------------------------------------------------------------------
# AI helpers
# ---------------------------------------------------------------------------

def ai_client():
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY не задан в .env")
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def get_or_create_quote(today: str) -> dict:
    with db() as conn:
        row = conn.execute("SELECT text, author FROM quotes WHERE date = ?", (today,)).fetchone()
        if row:
            return {"text": row["text"], "author": row["author"]}

    client = ai_client()
    prompt = (
        "Дай мне одну цитату от известного человека — писателя, художника, философа, "
        "режиссёра или предпринимателя. Тема: жизнь, смысл, красота, смелость, женственность, "
        "творчество, или просто что-то мудрое и нестандартное. "
        "Цитата должна быть короткой (1-2 предложения), умной, не банальной. "
        "Не выбирай одни и те же имена каждый раз — разнообразь источники. "
        "Ответь строго в JSON: {\"text\": \"текст цитаты\", \"author\": \"Имя, кто это\"}"
    )
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    # Extract JSON even if wrapped in markdown
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw.strip())

    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO quotes (date, text, author) VALUES (?, ?, ?)",
            (today, data["text"], data["author"]),
        )
    return data


def ai_evening_summary(done: list, undone: list) -> str:
    if not done and not undone:
        return "День прошёл. Завтра — новый."

    total = len(done) + len(undone)
    ratio = len(done) / total if total > 0 else 0

    if ratio >= 0.8:
        tone = "искренняя спокойная похвала без восклицаний и дежурных фраз"
    elif ratio >= 0.5:
        tone = "нейтрально, по-деловому, без оценок"
    else:
        tone = "поддерживающе, с пониманием, без осуждения и без жалости"

    done_titles = ", ".join(t["title"] for t in done[:8]) if done else "ничего"
    undone_titles = ", ".join(t["title"] for t in undone[:5]) if undone else "всё сделано"

    prompt = (
        f"Напиши итог рабочего дня для Ольги — женщины-предпринимателя. "
        f"Выполнено ({len(done)}): {done_titles}. "
        f"Не выполнено ({len(undone)}): {undone_titles}. "
        f"Тон: {tone}. "
        f"Правила: НИКАКИХ 'Вау!', 'Молодец!', 'Отлично!', 'Супер!'. "
        f"Максимум 2-3 предложения. Только текст, без заголовков."
    )
    client = ai_client()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def ai_parse_voice(text: str, today: str) -> dict:
    prompt = (
        f"Сегодня {today}. Пользователь надиктовал голосом — текст получен через распознавание речи, могут быть ошибки и опечатки: «{text}». "
        "Исправь очевидные ошибки распознавания и пойми смысл. Определи: это задача или идея. "
        "Если задача — сформулируй название чётко (исправив ошибки речи), определи тип и дату. "
        "Типы: work = работа/встречи/звонки/бизнес; personal = семья/дом/личные дела; rest = прогулка/отдых/спорт/спа/красота; growth = обучение/чтение/курсы/развитие. "
        "Если идея — кратко сформулируй суть и дату напоминания если упомянута. "
        "Дни недели считай от сегодня вперёд. Если сказано 'завтра' — следующий день, 'в пятницу' — ближайшая пятница. "
        "Ответь строго JSON без пояснений: "
        "{\"type\": \"task|idea\", \"title\": \"...\", "
        "\"task_type\": \"work|personal|rest|growth\", "
        "\"date\": \"YYYY-MM-DD или null\", "
        "\"time_start\": \"HH:MM или null\", "
        "\"remind_at\": \"YYYY-MM-DD или null\"}"
    )
    client = ai_client()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Personal Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TaskCreate(BaseModel):
    title: str
    type: str = "work"
    date: str
    time_start: Optional[str] = None
    project_id: Optional[int] = None
    is_buffer: Optional[bool] = False


class IdeaCreate(BaseModel):
    content: str
    remind_at: Optional[str] = None


class HorizonCreate(BaseModel):
    content: str
    timeframe: Optional[str] = None


class VoiceInput(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# Helper: row to dict
# ---------------------------------------------------------------------------

def row_to_dict(row) -> dict:
    return dict(row) if row else {}


def rows_to_list(rows) -> list:
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Routes: Morning & Evening
# ---------------------------------------------------------------------------

@app.get("/api/morning")
def morning():
    today = date.today().isoformat()
    quote = get_or_create_quote(today)

    with db() as conn:
        tasks = rows_to_list(
            conn.execute(
                "SELECT t.*, p.name as project_name, p.color as project_color "
                "FROM tasks t LEFT JOIN projects p ON t.project_id = p.id "
                "WHERE t.date = ? ORDER BY t.time_start NULLS LAST, t.created_at",
                (today,),
            ).fetchall()
        )

    work_tasks = [t for t in tasks if t["type"] == "work"]
    rest_tasks = [t for t in tasks if t["type"] == "rest"]
    warn_no_rest = len(work_tasks) >= 3 and len(rest_tasks) == 0

    return {
        "date": today,
        "quote": quote,
        "tasks": tasks,
        "warn_no_rest": warn_no_rest,
    }


@app.get("/api/evening")
def evening():
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    with db() as conn:
        all_today = rows_to_list(
            conn.execute(
                "SELECT t.*, p.name as project_name, p.color as project_color "
                "FROM tasks t LEFT JOIN projects p ON t.project_id = p.id "
                "WHERE t.date = ?",
                (today,),
            ).fetchall()
        )

        done = [t for t in all_today if t["completed"]]
        undone = [t for t in all_today if not t["completed"]]

        # Move undone tasks to tomorrow
        moved_ids = [t["id"] for t in undone]
        if moved_ids:
            placeholders = ",".join("?" * len(moved_ids))
            conn.execute(
                f"UPDATE tasks SET date = ? WHERE id IN ({placeholders})",
                [tomorrow] + moved_ids,
            )

        tomorrow_tasks = rows_to_list(
            conn.execute(
                "SELECT t.*, p.name as project_name, p.color as project_color "
                "FROM tasks t LEFT JOIN projects p ON t.project_id = p.id "
                "WHERE t.date = ? ORDER BY t.time_start NULLS LAST",
                (tomorrow,),
            ).fetchall()
        )

    summary = ai_evening_summary(done, undone)

    return {
        "date": today,
        "summary": summary,
        "completed": done,
        "moved": undone,
        "tomorrow": tomorrow_tasks,
    }


# ---------------------------------------------------------------------------
# Routes: Tasks
# ---------------------------------------------------------------------------

@app.get("/api/tasks")
def get_tasks(for_date: Optional[str] = None):
    target = for_date or date.today().isoformat()
    with db() as conn:
        tasks = rows_to_list(
            conn.execute(
                "SELECT t.*, p.name as project_name, p.color as project_color "
                "FROM tasks t LEFT JOIN projects p ON t.project_id = p.id "
                "WHERE t.date = ? ORDER BY t.time_start NULLS LAST, t.created_at",
                (target,),
            ).fetchall()
        )
    return tasks


@app.post("/api/tasks", status_code=201)
def create_task(body: TaskCreate):
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (title, type, date, time_start, project_id, is_buffer) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                body.title,
                body.type,
                body.date,
                body.time_start,
                body.project_id,
                1 if body.is_buffer else 0,
            ),
        )
        task_id = cur.lastrowid
        task = row_to_dict(
            conn.execute(
                "SELECT t.*, p.name as project_name, p.color as project_color "
                "FROM tasks t LEFT JOIN projects p ON t.project_id = p.id WHERE t.id = ?",
                (task_id,),
            ).fetchone()
        )
    return task


@app.put("/api/tasks/{task_id}")
def update_task(task_id: int, body: TaskCreate):
    with db() as conn:
        row = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        conn.execute(
            "UPDATE tasks SET title=?, type=?, date=?, time_start=?, project_id=? WHERE id=?",
            (body.title, body.type, body.date, body.time_start, body.project_id, task_id),
        )
        task = row_to_dict(
            conn.execute(
                "SELECT t.*, p.name as project_name, p.color as project_color "
                "FROM tasks t LEFT JOIN projects p ON t.project_id = p.id WHERE t.id = ?",
                (task_id,),
            ).fetchone()
        )
    return task


@app.put("/api/tasks/{task_id}/toggle")
def toggle_task(task_id: int):
    with db() as conn:
        row = conn.execute("SELECT completed FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        new_val = 0 if row["completed"] else 1
        conn.execute("UPDATE tasks SET completed = ? WHERE id = ?", (new_val, task_id))
        task = row_to_dict(
            conn.execute(
                "SELECT t.*, p.name as project_name, p.color as project_color "
                "FROM tasks t LEFT JOIN projects p ON t.project_id = p.id WHERE t.id = ?",
                (task_id,),
            ).fetchone()
        )
    return task


@app.get("/api/calendar")
def get_calendar(year: int, month: int):
    with db() as conn:
        rows = conn.execute(
            "SELECT date, COUNT(*) as cnt FROM tasks "
            "WHERE strftime('%Y', date) = ? AND strftime('%m', date) = ? "
            "GROUP BY date",
            (str(year), f"{month:02d}"),
        ).fetchall()
    return {row["date"]: row["cnt"] for row in rows}


@app.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(task_id: int):
    with db() as conn:
        row = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))


# ---------------------------------------------------------------------------
# Routes: Voice
# ---------------------------------------------------------------------------

@app.post("/api/voice")
def voice_input(body: VoiceInput):
    today = date.today().isoformat()
    parsed = ai_parse_voice(body.text, today)

    item_type = parsed.get("type", "idea")

    if item_type == "task":
        task_date = parsed.get("date") or today
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO tasks (title, type, date, time_start) VALUES (?, ?, ?, ?)",
                (
                    parsed.get("title", body.text[:100]),
                    parsed.get("task_type", "work"),
                    task_date,
                    parsed.get("time_start"),
                ),
            )
            new_id = cur.lastrowid
        return {
            "type": "task",
            "id": new_id,
            "message": f"Задача добавлена на {task_date}",
            "parsed": parsed,
        }
    else:
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO ideas (content, remind_at) VALUES (?, ?)",
                (parsed.get("title", body.text), parsed.get("remind_at")),
            )
            new_id = cur.lastrowid
        return {
            "type": "idea",
            "id": new_id,
            "message": "Идея сохранена",
            "parsed": parsed,
        }


# ---------------------------------------------------------------------------
# Routes: Projects
# ---------------------------------------------------------------------------

@app.get("/api/projects")
def get_projects():
    with db() as conn:
        projects = rows_to_list(conn.execute("SELECT * FROM projects ORDER BY id").fetchall())
    return projects


# ---------------------------------------------------------------------------
# Routes: Ideas
# ---------------------------------------------------------------------------

@app.get("/api/ideas")
def get_ideas():
    with db() as conn:
        ideas = rows_to_list(
            conn.execute(
                "SELECT * FROM ideas WHERE status = 'pending' ORDER BY created_at DESC"
            ).fetchall()
        )
    return ideas


@app.post("/api/ideas", status_code=201)
def create_idea(body: IdeaCreate):
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO ideas (content, remind_at) VALUES (?, ?)",
            (body.content, body.remind_at),
        )
        idea = row_to_dict(
            conn.execute("SELECT * FROM ideas WHERE id = ?", (cur.lastrowid,)).fetchone()
        )
    return idea


@app.put("/api/ideas/{idea_id}/archive")
def archive_idea(idea_id: int):
    with db() as conn:
        row = conn.execute("SELECT id FROM ideas WHERE id = ?", (idea_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Идея не найдена")
        conn.execute("UPDATE ideas SET status = 'archived' WHERE id = ?", (idea_id,))
        idea = row_to_dict(
            conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
        )
    return idea


# ---------------------------------------------------------------------------
# Routes: Horizon
# ---------------------------------------------------------------------------

@app.get("/api/horizon")
def get_horizon():
    with db() as conn:
        items = rows_to_list(
            conn.execute("SELECT * FROM horizon ORDER BY created_at DESC").fetchall()
        )
    return items


@app.post("/api/horizon", status_code=201)
def create_horizon(body: HorizonCreate):
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO horizon (content, timeframe) VALUES (?, ?)",
            (body.content, body.timeframe),
        )
        item = row_to_dict(
            conn.execute("SELECT * FROM horizon WHERE id = ?", (cur.lastrowid,)).fetchone()
        )
    return item


@app.delete("/api/horizon/{item_id}", status_code=204)
def delete_horizon(item_id: int):
    with db() as conn:
        row = conn.execute("SELECT id FROM horizon WHERE id = ?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Намерение не найдено")
        conn.execute("DELETE FROM horizon WHERE id = ?", (item_id,))


# ---------------------------------------------------------------------------
# Serve frontend as static files
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory=FRONTEND_PATH, html=True), name="frontend")

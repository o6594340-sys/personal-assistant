import os
import json
import uuid
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

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
_data_dir = os.getenv("DATA_DIR", os.path.dirname(__file__))
DB_PATH = os.path.join(_data_dir, "assistant.db")
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

        # Migrations
        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN recurrence_id TEXT")
        except Exception:
            pass

        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN date_end TEXT")
        except Exception:
            pass

        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN time_end TEXT")
        except Exception:
            pass

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
    import hashlib
    categories = [
        "художник или скульптор (Фрида Кало, Пикассо, Да Винчи, Дали, Ван Гог, Климт, Шагал, Матисс и другие)",
        "поэт или писатель (Цветаева, Ахматова, Рильке, Кафка, Буковски, Борхес, Вирджиния Вулф, Сильвия Плат и другие)",
        "композитор или музыкант (Моцарт, Бах, Дебюсси, Шопен, Джон Леннон, Дэвид Боуи, Нина Симон и другие)",
        "философ или мыслитель (Ницше, Симона де Бовуар, Сенека, Марк Аврелий, Камю, Сартр, Хайдеггер и другие)",
        "режиссёр или кинематографист (Феллини, Тарковский, Бергман, Вонг Кар-Вай, Одри Хепберн, Марлен Дитрих и другие)",
        "предприниматель или дизайнер (Коко Шанель, Стив Джобс, Илон Маск, Ив Сен-Лоран, Карл Лагерфельд и другие)",
        "учёный или первооткрыватель (Мария Кюри, Эйнштейн, Фейнман, Дарвин, Тесла и другие)",
        "актриса или деятель культуры (Мэрил Стрип, Катрин Денёв, Майя Плисецкая, Одри Хепберн, Грейс Келли и другие)",
    ]
    day_of_year = int(hashlib.md5(today.encode()).hexdigest(), 16) % len(categories)
    category = categories[day_of_year]
    prompt = (
        f"Дай мне одну настоящую, документально подтверждённую цитату от известного человека из категории: {category}. "
        "Тема цитаты: жизнь, смысл, красота, творчество, смелость, женственность, любовь, время, свобода — "
        "что-то мудрое, нестандартное и живое. "
        "Цитата должна быть короткой (1-3 предложения), не банальной, не мотивационный плакат. "
        "Выбери конкретного человека, которого ты ещё не упоминал сегодня. "
        "Ответь строго в JSON без markdown: {\"text\": \"текст цитаты на русском\", \"author\": \"Имя, кто это\"}"
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


_WEEKDAY_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def generate_recurring_dates(recurrence: str, recurrence_days: list, date_start: str, date_until: str | None) -> list[str]:
    target = [_WEEKDAY_MAP[d.lower()] for d in (recurrence_days or []) if d.lower() in _WEEKDAY_MAP]
    start = date.fromisoformat(date_start)
    end = date.fromisoformat(date_until) if date_until else start + timedelta(days=365)
    result = []
    cur = start
    while cur <= end:
        if recurrence == "weekly" and cur.weekday() in target:
            result.append(cur.isoformat())
        elif recurrence == "daily":
            result.append(cur.isoformat())
        cur += timedelta(days=1)
    return result


def ai_parse_voice(text: str, today: str) -> list:
    prompt = (
        f"Сегодня {today}. Пользователь надиктовал голосом (могут быть ошибки распознавания): «{text}». "
        "Исправь ошибки. Из title УБЕРИ служебные слова: 'добавить', 'добавь', 'напомни', 'поставь задачу', 'записать идеи', 'идеи на неделю' и подобные — в title только суть. "
        "ВАЖНО: если перечислено несколько пунктов (1,2,3... или через запятую/перечисление) — создай ОТДЕЛЬНЫЙ объект для каждого пункта. "
        "ЕСЛИ сказано 'идеи' или 'набросать идеи' или 'идеи на неделю' — все пункты это idea, date=null. "
        "ЕСЛИ упомянуты повторения (каждый понедельник, ежедневно и т.д.) — это recurring_task. "
        "ЕСЛИ упомянут диапазон дней (с ... по ...) — это task с date_end. "
        "Типы задач: work=работа/встречи/бизнес; personal=семья/дом/личное; rest=прогулка/отдых/спорт/красота; growth=обучение/развитие. "
        "Дни недели вперёд от сегодня. "
        "Для recurrence_days используй английские названия: monday/tuesday/wednesday/thursday/friday/saturday/sunday. "
        "Ответь строго JSON-массивом без пояснений (даже если один элемент — всё равно массив): "
        "[{\"type\": \"task|recurring_task|idea\", \"title\": \"...\", "
        "\"task_type\": \"work|personal|rest|growth\", "
        "\"date\": \"YYYY-MM-DD или null\", "
        "\"date_end\": \"YYYY-MM-DD или null\", "
        "\"time_start\": \"HH:MM или null\", "
        "\"time_end\": \"HH:MM или null\", "
        "\"remind_at\": \"YYYY-MM-DD или null\", "
        "\"recurrence\": \"weekly|daily|null\", "
        "\"recurrence_days\": [], "
        "\"date_until\": \"YYYY-MM-DD или null\"}, ...]"
    )
    client = ai_client()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw.strip())
    return result if isinstance(result, list) else [result]


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
    date_end: Optional[str] = None
    time_start: Optional[str] = None
    time_end: Optional[str] = None
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

_FALLBACK_QUOTES = [
    # Художники
    {"text": "Я плачу, потому что не могу нарисовать этого так хорошо, как чувствую.", "author": "Фрида Кало, художник"},
    {"text": "Всё, что ты можешь себе представить — реально.", "author": "Пабло Пикассо, художник"},
    {"text": "Живопись — это поэзия, которую видят, а не слышат.", "author": "Леонардо да Винчи, художник и учёный"},
    {"text": "Я мечтаю о картинах, а потом рисую свои мечты.", "author": "Винсент Ван Гог, художник"},
    {"text": "Искусство — это ложь, которая помогает понять правду.", "author": "Пабло Пикассо, художник"},
    {"text": "Цвет — это клавиатура. Глаз — это молоточек. Душа — это рояль со многими струнами.", "author": "Василий Кандинский, художник"},
    {"text": "Всё в жизни — это либо секс, либо ожидание секса, либо усталость от секса.", "author": "Сальвадор Дали, художник"},
    {"text": "Нет ничего более реального, чем то, чего мы не видим.", "author": "Гюстав Флобер, писатель"},
    # Поэты и писатели
    {"text": "Я хочу жить так, чтобы даже мои ошибки стали стихами.", "author": "Марина Цветаева, поэт"},
    {"text": "Не надо мне ни счастья, ни покоя — дай только видеть звёзды ночью тёмной.", "author": "Марина Цветаева, поэт"},
    {"text": "Мне от тебя нужна была не вечность, а только этот момент.", "author": "Анна Ахматова, поэт"},
    {"text": "Красота спасёт мир.", "author": "Фёдор Достоевский, писатель"},
    {"text": "Если ты не можешь летать — беги. Если не можешь бежать — иди. Если не можешь идти — ползи. Но двигайся.", "author": "Мартин Лютер Кинг"},
    {"text": "Живи так, чтобы тебе не было стыдно за то, что ты делаешь, даже если никто об этом не узнает.", "author": "Конфуций, философ"},
    {"text": "Мир полон магии. Нужно только уметь её увидеть.", "author": "Вирджиния Вулф, писатель"},
    {"text": "Нет ничего страшнее, чем ничего не делать.", "author": "Франц Кафка, писатель"},
    {"text": "Я не боюсь бури. Я учусь управлять кораблём.", "author": "Луиза Мэй Олкотт, писатель"},
    {"text": "Единственный путь выйти — это пройти сквозь.", "author": "Роберт Фрост, поэт"},
    {"text": "Смелость — это не отсутствие страха, а суждение о том, что нечто важнее страха.", "author": "Амброз Бирс, писатель"},
    # Философы
    {"text": "То, что нас не убивает, делает нас сильнее.", "author": "Фридрих Ницше, философ"},
    {"text": "Человек — это канат, натянутый между животным и сверхчеловеком.", "author": "Фридрих Ницше, философ"},
    {"text": "Я думаю, следовательно, я существую.", "author": "Рене Декарт, философ"},
    {"text": "Единственное благо — знание. Единственное зло — невежество.", "author": "Сократ, философ"},
    {"text": "Счастье — это не то, что ты имеешь, а то, кем ты являешься.", "author": "Паоло Коэльо, писатель"},
    {"text": "Жизнь — это то, что с тобой происходит, пока ты занят другими планами.", "author": "Аллен Сандерс"},
    {"text": "Потеряв деньги — потерял немного. Потеряв честь — потерял много. Потеряв смелость — потерял всё.", "author": "Уинстон Черчилль"},
    {"text": "Самое тёмное время — перед рассветом.", "author": "Томас Фуллер, философ"},
    {"text": "Мы — то, что мы делаем постоянно. Превосходство — это не действие, а привычка.", "author": "Аристотель, философ"},
    {"text": "Никогда не поздно стать тем, кем ты мог бы быть.", "author": "Джордж Элиот, писатель"},
    # Музыканты и композиторы
    {"text": "Музыка — это откровение выше мудрости и философии.", "author": "Людвиг Ван Бетховен, композитор"},
    {"text": "Жизнь без музыки — это ошибка.", "author": "Фридрих Ницше, философ"},
    {"text": "Без отклонений от нормы прогресс невозможен.", "author": "Фрэнк Заппа, музыкант"},
    {"text": "Мечты не сбываются — их осуществляют.", "author": "Джон Леннон, музыкант"},
    {"text": "Я начинаю там, где заканчивается правило.", "author": "Коко Шанель, дизайнер"},
    {"text": "Лучший способ предсказать будущее — создать его.", "author": "Питер Друкер, теоретик менеджмента"},
    # Режиссёры и кино
    {"text": "Кино — это правда 24 кадра в секунду.", "author": "Жан-Люк Годар, режиссёр"},
    {"text": "Если вы хотите рассказать людям правду — заставьте их смеяться, иначе они убьют вас.", "author": "Оскар Уайльд, писатель"},
    {"text": "Я не снимаю кино о том, что происходит. Я снимаю о том, что чувствуется.", "author": "Андрей Тарковский, режиссёр"},
    {"text": "Сны — это ответы на вопросы, которые мы ещё не научились задавать.", "author": "Федерико Феллини, режиссёр"},
    # Женщины — деятели и предпринимательницы
    {"text": "Мода — это не просто одежда. Мода — это жизнь.", "author": "Коко Шанель, дизайнер"},
    {"text": "Красивая женщина нравится глазам. Добрая — сердцу.", "author": "Виктор Гюго, писатель"},
    {"text": "Чтобы быть незаменимой, нужно всегда быть разной.", "author": "Коко Шанель, дизайнер"},
    {"text": "Я не хочу жить вечно благодаря своим работам. Я хочу жить вечно, не умирая.", "author": "Вуди Аллен, режиссёр"},
    {"text": "Всё стоит того, если душа не маленькая.", "author": "Фернандо Пессоа, поэт"},
    {"text": "Смелость — это решение, что что-то другое важнее страха.", "author": "Амброз Редмун"},
    # Учёные
    {"text": "Воображение важнее знания.", "author": "Альберт Эйнштейн, физик"},
    {"text": "Там, где заканчивается элегантность, начинается сложность.", "author": "Мария Кюри, учёный"},
    {"text": "Наука — это организованные знания. Мудрость — это организованная жизнь.", "author": "Иммануил Кант, философ"},
    {"text": "Жизнь требует не идеальных условий. Жизнь требует начала.", "author": "Мария Кюри, учёный"},
    {"text": "Если вы думаете, что можете — вы правы. Если думаете, что не можете — тоже правы.", "author": "Генри Форд, предприниматель"},
    # Разное
    {"text": "Дерево, которое было гибким, выжило в бурю.", "author": "Лао-Цзы, философ"},
    {"text": "Жизнь коротка. Улыбайся, пока зубы ещё целые.", "author": "Мэрилин Монро, актриса"},
    {"text": "Я никогда не мечтала об успехе. Я работала ради него.", "author": "Эстée Лодер, предприниматель"},
    {"text": "Делай, что можешь, с тем, что имеешь, там, где ты есть.", "author": "Теодор Рузвельт"},
    {"text": "Всё великое начинается с маленького шага.", "author": "Лао-Цзы, философ"},
    {"text": "Когда одна дверь закрывается — другая открывается. Но мы так долго смотрим на закрытую дверь, что не видим открытой.", "author": "Александр Грэм Белл, изобретатель"},
    {"text": "Настоящая роскошь — это позволить себе быть собой.", "author": "Коко Шанель, дизайнер"},
    {"text": "Я никогда не теряю. Либо я побеждаю, либо я учусь.", "author": "Нельсон Мандела"},
    {"text": "Покой — не отдых. Покой — это смерть.", "author": "Пабло Пикассо, художник"},
    {"text": "Тихая вода берега рвёт.", "author": "Русская пословица"},
]


def rollover_past_tasks(today: str):
    """Move uncompleted single-day tasks from past dates to today."""
    with db() as conn:
        conn.execute(
            "UPDATE tasks SET date = ? "
            "WHERE date < ? AND completed = 0 AND (date_end IS NULL OR date_end < ?)",
            (today, today, today),
        )


@app.get("/api/morning")
def morning():
    today = date.today().isoformat()
    rollover_past_tasks(today)

    try:
        quote = get_or_create_quote(today)
    except Exception:
        import hashlib
        idx = int(hashlib.md5(today.encode()).hexdigest(), 16) % len(_FALLBACK_QUOTES)
        quote = _FALLBACK_QUOTES[idx]

    with db() as conn:
        tasks = rows_to_list(
            conn.execute(
                "SELECT t.*, p.name as project_name, p.color as project_color "
                "FROM tasks t LEFT JOIN projects p ON t.project_id = p.id "
                "WHERE t.date <= ? AND COALESCE(t.date_end, t.date) >= ? "
                "ORDER BY t.time_start NULLS LAST, t.created_at",
                (today, today),
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

    try:
        summary = ai_evening_summary(done, undone)
    except Exception:
        done_count = len(done)
        total = done_count + len(undone)
        summary = f"День завершён. Выполнено {done_count} из {total} задач." if total else "День завершён."

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
                "WHERE t.date <= ? AND COALESCE(t.date_end, t.date) >= ? "
                "ORDER BY t.time_start NULLS LAST, t.created_at",
                (target, target),
            ).fetchall()
        )
    return tasks


@app.post("/api/tasks", status_code=201)
def create_task(body: TaskCreate):
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (title, type, date, date_end, time_start, time_end, project_id, is_buffer) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                body.title,
                body.type,
                body.date,
                body.date_end,
                body.time_start,
                body.time_end,
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
            "UPDATE tasks SET title=?, type=?, date=?, date_end=?, time_start=?, time_end=?, project_id=? WHERE id=?",
            (body.title, body.type, body.date, body.date_end, body.time_start, body.time_end, body.project_id, task_id),
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


@app.get("/api/tasks/week")
def get_week_tasks(start_date: str):
    start = date.fromisoformat(start_date)
    result = {}
    with db() as conn:
        for i in range(7):
            d = start + timedelta(days=i)
            iso = d.isoformat()
            rows = rows_to_list(
                conn.execute(
                    "SELECT t.*, p.name AS project_name, p.color AS project_color "
                    "FROM tasks t LEFT JOIN projects p ON t.project_id = p.id "
                    "WHERE t.date <= ? AND COALESCE(t.date_end, t.date) >= ? "
                    "ORDER BY t.time_start NULLS LAST, t.created_at",
                    (iso, iso),
                ).fetchall()
            )
            result[iso] = rows
    return result


@app.get("/api/calendar")
def get_calendar(year: int, month: int):
    month_str = f"{month:02d}"
    year_str = str(year)
    first_day = f"{year_str}-{month_str}-01"
    last_day = (date(year, month + 1, 1) - timedelta(days=1)).isoformat() if month < 12 else f"{year_str}-12-31"

    with db() as conn:
        rows = conn.execute(
            "SELECT date, COUNT(*) as cnt FROM tasks "
            "WHERE strftime('%Y', date) = ? AND strftime('%m', date) = ? "
            "GROUP BY date",
            (year_str, month_str),
        ).fetchall()
        span_rows = conn.execute(
            "SELECT date, date_end FROM tasks "
            "WHERE date_end IS NOT NULL AND date_end >= ? AND date <= ?",
            (first_day, last_day),
        ).fetchall()

    result = {row["date"]: row["cnt"] for row in rows}

    span_days = {}
    for span in span_rows:
        start = date.fromisoformat(span["date"])
        end = date.fromisoformat(span["date_end"])
        cur = start
        while cur <= end:
            iso = cur.isoformat()
            if first_day <= iso <= last_day and iso not in span_days:
                span_days[iso] = "start" if cur == start else ("end" if cur == end else "mid")
            cur += timedelta(days=1)

    if span_days:
        result["_spans"] = span_days
    return result


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

def _save_parsed_item(parsed: dict, today: str, fallback_text: str) -> dict:
    item_type = parsed.get("type", "idea")
    title = parsed.get("title") or fallback_text[:100]
    task_type = parsed.get("task_type", "personal")
    time_start = parsed.get("time_start")

    if item_type == "recurring_task" or (item_type == "task" and parsed.get("recurrence")):
        rec_id = uuid.uuid4().hex[:10]
        dates = generate_recurring_dates(
            parsed.get("recurrence", "weekly"),
            parsed.get("recurrence_days", []),
            parsed.get("date") or today,
            parsed.get("date_until"),
        )
        if dates:
            with db() as conn:
                for d in dates:
                    conn.execute(
                        "INSERT INTO tasks (title, type, date, time_start, recurrence_id) VALUES (?, ?, ?, ?, ?)",
                        (title, task_type, d, time_start, rec_id),
                    )
        return {"type": "task", "recurring": True, "count": len(dates), "title": title}

    if item_type in ("task", "recurring_task"):
        task_date = parsed.get("date") or today
        with db() as conn:
            conn.execute(
                "INSERT INTO tasks (title, type, date, date_end, time_start, time_end) VALUES (?, ?, ?, ?, ?, ?)",
                (title, task_type, task_date, parsed.get("date_end"), time_start, parsed.get("time_end")),
            )
        return {"type": "task", "title": title, "date": task_date}

    with db() as conn:
        conn.execute(
            "INSERT INTO ideas (content, remind_at) VALUES (?, ?)",
            (title, parsed.get("remind_at")),
        )
    return {"type": "idea", "title": title}


@app.post("/api/voice")
def voice_input(body: VoiceInput):
    today = date.today().isoformat()
    try:
        items = ai_parse_voice(body.text, today)
    except Exception:
        items = [{
            "type": "task",
            "title": body.text[:200].strip(),
            "task_type": "personal",
            "date": today,
            "date_end": None, "time_start": None, "time_end": None,
            "remind_at": None, "recurrence": None, "recurrence_days": [], "date_until": None,
        }]

    saved = [_save_parsed_item(p, today, body.text) for p in items]

    tasks = [s for s in saved if s["type"] == "task"]
    ideas = [s for s in saved if s["type"] == "idea"]

    if len(saved) == 1:
        s = saved[0]
        if s["type"] == "idea":
            message = f"Идея сохранена: «{s['title']}»"
        else:
            message = f"Задача добавлена на {s.get('date', today)}: «{s['title']}»"
    else:
        parts = []
        if tasks:
            parts.append(f"задач: {len(tasks)}")
        if ideas:
            parts.append(f"идей: {len(ideas)}")
        message = f"Добавлено {' и '.join(parts)}"

    return {"type": saved[0]["type"] if len(saved) == 1 else "multi", "message": message, "saved": saved}


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
# Diagnostic
# ---------------------------------------------------------------------------

@app.post("/api/quote/refresh")
def refresh_quote():
    today = date.today().isoformat()
    with db() as conn:
        conn.execute("DELETE FROM quotes WHERE date = ?", (today,))
    try:
        quote = get_or_create_quote(today)
    except Exception:
        import hashlib
        idx = int(hashlib.md5(today.encode()).hexdigest(), 16) % len(_FALLBACK_QUOTES)
        quote = _FALLBACK_QUOTES[idx]
    return quote


@app.get("/api/health")
def health():
    import traceback
    result = {"db": "ok", "anthropic_key": bool(ANTHROPIC_API_KEY), "anthropic": None, "error": None}
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": "hi"}],
        )
        result["anthropic"] = "ok"
    except Exception as e:
        result["anthropic"] = "error"
        result["error"] = traceback.format_exc()
    return result


# ---------------------------------------------------------------------------
# Serve frontend as static files
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory=FRONTEND_PATH, html=True), name="frontend")

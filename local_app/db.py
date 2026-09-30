from __future__ import annotations
import csv, json, sqlite3
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/"source"
DB_PATH=ROOT/"data"/"fill_form.db"

def connect():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DB_PATH,timeout=30)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db

def ensure_column(db,table,column,declaration):
    columns={row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
    if column not in columns: db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

def init_db():
    db=connect()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS forms(id TEXT PRIMARY KEY,title TEXT NOT NULL,config_path TEXT NOT NULL,data_path TEXT NOT NULL,question_count INTEGER NOT NULL,monthly_target INTEGER NOT NULL DEFAULT 30,active INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS staff(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,degree TEXT NOT NULL,department TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,UNIQUE(name,degree,department));
    CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY AUTOINCREMENT,period TEXT NOT NULL,form_ids TEXT NOT NULL,requested_count INTEGER NOT NULL,dry_run INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'queued',done INTEGER NOT NULL DEFAULT 0,total INTEGER NOT NULL DEFAULT 0,message TEXT DEFAULT '',stop_requested INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,started_at TEXT,finished_at TEXT);
    CREATE TABLE IF NOT EXISTS monthly_plans(period TEXT PRIMARY KEY,form_id TEXT NOT NULL,target INTEGER NOT NULL DEFAULT 30,selected_list_ids TEXT NOT NULL DEFAULT '["ctch"]',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS submissions(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id INTEGER,period TEXT NOT NULL,form_id TEXT NOT NULL,form_title TEXT NOT NULL,submitted_at TEXT NOT NULL,row_index INTEGER,name TEXT,degree TEXT,department TEXT,list_id TEXT,score_total INTEGER,score_max INTEGER,score_percent REAL,scores TEXT,comment TEXT,status TEXT NOT NULL,error TEXT,submission_key TEXT UNIQUE,dry_run INTEGER NOT NULL DEFAULT 0);
    CREATE INDEX IF NOT EXISTS idx_submissions_period ON submissions(period);
    """)
    ensure_column(db,"jobs","selected_list_ids","TEXT NOT NULL DEFAULT '[\"ctch\"]'")
    ensure_column(db,"submissions","record_json","TEXT")
    db.execute("CREATE INDEX IF NOT EXISTS idx_submissions_lookup ON submissions(period,form_id,department,status)")
    jobs=list(csv.DictReader((SOURCE/"jobs.csv").open(encoding="utf-8-sig")))
    for j in jobs:
        cfg=json.loads((SOURCE/j["config_path"]).read_text(encoding="utf-8")); fields=cfg.get("fields",[])
        q=int(cfg.get("score_count") or sum(1 for x in fields if x.get("type")=="radio_in_section"))
        db.execute("INSERT INTO forms VALUES(?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET title=excluded.title,config_path=excluded.config_path,data_path=excluded.data_path,question_count=excluded.question_count",(j["job_id"],cfg.get("title",j["job_id"]),j["config_path"],j["data_path"],q,int(j.get("max_success",30))))
    roster=json.loads((SOURCE/"roster.json").read_text(encoding="utf-8"))
    for dept,block in roster.items():
        for degree,names in block.items():
            for name in names: db.execute("INSERT OR IGNORE INTO staff(name,degree,department) VALUES(?,?,?)",(name,degree,dept))
    # Nhập lịch sử schema mới một lần, giữ nguyên ngày thực tế.
    if db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]==0:
        titles={r["id"]:r["title"] for r in db.execute("SELECT id,title FROM forms")}
        for path in (SOURCE/"history").glob("*.csv") if (SOURCE/"history").exists() else []:
            for row in csv.DictReader(path.open(encoding="utf-8-sig")):
                if not row.get("submitted_at") or not row.get("name"): continue
                fid=path.stem; when=row["submitted_at"]; period=when[:7]
                key=f"import:{fid}:{when}:{row.get('name')}:{row.get('row_index')}"
                db.execute("INSERT OR IGNORE INTO submissions(period,form_id,form_title,submitted_at,row_index,name,degree,department,list_id,score_total,score_max,score_percent,scores,status,submission_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(period,fid,titles.get(fid,fid),when,row.get("row_index"),row.get("name"),row.get("degree"),row.get("department"),row.get("list_id"),row.get("score_total"),row.get("score_max"),row.get("score_percent"),row.get("scores"),"success",key))
    # Lập danh sách tháng cũ: mỗi tháng chọn biểu mẫu có nhiều kết quả hợp lệ nhất.
    for period_row in db.execute("SELECT DISTINCT period FROM submissions WHERE dry_run=0"):
        selected=db.execute("SELECT form_id,COUNT(*) AS n FROM submissions WHERE period=? AND status='success' AND dry_run=0 GROUP BY form_id ORDER BY n DESC,form_id LIMIT 1",(period_row["period"],)).fetchone()
        if selected: db.execute("INSERT OR IGNORE INTO monthly_plans(period,form_id,created_at,updated_at) VALUES(?,?,?,?)",(period_row["period"],selected["form_id"],now(),now()))
    db.commit();db.close()

def now(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

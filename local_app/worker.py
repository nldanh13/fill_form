from __future__ import annotations
import csv, hashlib, importlib.util, json, random, sys, traceback
from db import connect,init_db,now,ROOT,SOURCE

def load_legacy():
    spec=importlib.util.spec_from_file_location("legacy_runner",SOURCE/"legacy_runner.py")
    mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod);return mod
def make_key(fid,period,row,name,scores): return hashlib.sha1(f"{fid}|{period}|{row}|{name}|{'-'.join(scores)}".encode()).hexdigest()
def archive_record(record):
    folder=ROOT/"data"/"archive";folder.mkdir(parents=True,exist_ok=True)
    with (folder/f"{record['period']}.jsonl").open("a",encoding="utf-8") as output: output.write(json.dumps(record,ensure_ascii=False)+"\n")

def run(job_id):
    init_db();db=connect();job=db.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
    if not job:return
    db.execute("UPDATE jobs SET status='running',started_at=?,message='Đang nạp cấu hình' WHERE id=?",(now(),job_id));db.commit()
    legacy=load_legacy();profile=legacy.load_json(SOURCE/"profile.json");roster=legacy.load_json(SOURCE/"roster.json");bank=legacy.load_json(SOURCE/"comment_bank.json");lists=legacy.load_staff_lists(roster)
    context=page=pw=None
    try:
        form_ids=json.loads(job["form_ids"]);requested=int(job["requested_count"]);dry=bool(job["dry_run"]);done=0;selected_lists=json.loads(job["selected_list_ids"] or '["ctch"]')
        if not dry:
            if legacy.sync_playwright is None:
                raise RuntimeError("Chưa cài Playwright. Hãy chạy start_windows.bat để cài tự động.")
            pw=legacy.sync_playwright().start();context=pw.chromium.launch_persistent_context(user_data_dir=str(ROOT/"data"/"browser_profile"),headless=False,viewport={"width":1400,"height":900});page=context.pages[0] if context.pages else context.new_page()
        for fid in form_ids:
            form=db.execute("SELECT * FROM forms WHERE id=?",(fid,)).fetchone();cfg=legacy.normalize_config(legacy.load_json(SOURCE/form["config_path"]),SOURCE/form["config_path"])
            rows=list(csv.DictReader((SOURCE/form["data_path"]).open(encoding="utf-8-sig")))
            current=db.execute("SELECT COUNT(*) FROM submissions WHERE period=? AND form_id=? AND status='success' AND dry_run=0",(job["period"],fid)).fetchone()[0]
            allowed=max(0,min(requested,int(form["monthly_target"])-current))
            pool=(
                [legacy.StaffRecord("Không áp dụng","","","anonymous","Không áp dụng")]
                if cfg.get("anonymous")
                else legacy.build_staff_pool(roster,lists,selected_lists,cfg)
            );usage={}
            if not cfg.get("anonymous"):
                active_staff={(r["name"],r["degree"],r["department"]) for r in db.execute("SELECT name,degree,department FROM staff WHERE active=1")}
                pool=[s for s in pool if (s.name,s.degree,s.department) in active_staff]
                if not pool: raise RuntimeError("Không còn nhân sự đang hoạt động phù hợp với biểu mẫu.")
            for r in db.execute("SELECT name,department,list_id,COUNT(*) n FROM submissions WHERE form_id=? AND status='success' GROUP BY name,department,list_id",(fid,)):usage[(r["list_id"] or "",r["department"] or "",r["name"] or "")]=r["n"]
            if not dry:legacy.ensure_access(page,cfg["view_url"])
            success=attempt=0;row_order=list(range(len(rows)));random.shuffle(row_order)
            while success<allowed and attempt<max(len(rows)*len(pool),allowed*3):
                if db.execute("SELECT stop_requested FROM jobs WHERE id=?",(job_id,)).fetchone()[0]:
                    db.execute("UPDATE jobs SET status='stopped',finished_at=?,message='Đã dừng an toàn' WHERE id=?",(now(),job_id));db.commit();return
                if attempt and attempt%len(rows)==0: random.shuffle(row_order)
                row_no=row_order[attempt%len(rows)]+1;row=rows[row_no-1];scores=legacy.extract_scores(row,len(cfg["score_fields"]));attempt+=1
                staff=legacy.choose_staff_from_pool(pool,staff_usage_counts=usage);subkey=make_key(fid,job["period"],row_no,staff.name,scores)
                if db.execute("SELECT 1 FROM submissions WHERE submission_key=?",(subkey,)).fetchone():continue
                total,maximum,percent=legacy.score_percent(scores);comment=legacy.build_comment(bank,fid,cfg);status="preview" if dry else "success";error=None
                try:
                    if not dry:legacy.submit_legacy_form(page,cfg,profile,row,staff.name,staff.degree,staff.department,comment,scores)
                except Exception as exc:status="failed";error=str(exc)
                submitted_at=now();record={"schema_version":1,"record_id":subkey,"period":job["period"],"submitted_at":submitted_at,"form":{"id":fid,"title":form["title"]},"respondent":{"name":staff.name,"degree":staff.degree,"department":staff.department,"list_id":staff.list_id},"source":{"row_index":row_no,"values":row},"evaluation":{"scores":scores,"score_total":total,"score_max":maximum,"score_percent":percent,"comment":comment},"delivery":{"status":status,"error":error,"dry_run":dry}}
                cur=db.execute("INSERT OR IGNORE INTO submissions(job_id,period,form_id,form_title,submitted_at,row_index,name,degree,department,list_id,score_total,score_max,score_percent,scores,comment,status,error,submission_key,dry_run,record_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(job_id,job["period"],fid,form["title"],submitted_at,row_no,staff.name,staff.degree,staff.department,staff.list_id,total,maximum,percent,"-".join(scores),comment,status,error,subkey,int(dry),json.dumps(record,ensure_ascii=False)))
                if cur.rowcount and not dry: archive_record(record)
                done+=1;success+=status in ("success","preview");db.execute("UPDATE jobs SET done=?,message=? WHERE id=?",(done,f"{form['title']}: {success}/{allowed}",job_id));db.commit()
                if status=="failed":break
        db.execute("UPDATE jobs SET status='completed',finished_at=?,message=? WHERE id=?",(now(),"Chạy thử hoàn tất" if dry else "Đã hoàn thành",job_id));db.commit()
    except Exception as exc:
        db.execute("UPDATE jobs SET status='failed',finished_at=?,message=? WHERE id=?",(now(),str(exc),job_id));db.commit();traceback.print_exc()
    finally:
        if context:context.close()
        if pw:pw.stop()
        db.close()
if __name__=="__main__":run(int(sys.argv[1]))

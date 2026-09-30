from __future__ import annotations
import csv, io, json, sqlite3, subprocess, sys, zipfile
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs,urlparse
from db import connect,init_db,now,ROOT,SOURCE,DB_PATH

def settings_info():
    profile_path=SOURCE/"profile.json"
    profile=json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {}
    browser_profile=ROOT/"data"/"browser_profile"
    return {"email":profile.get("email","") ,"browser_profile_exists":browser_profile.exists(),"backup_dir":str(ROOT/"data"/"backups")}

def create_backup():
    stamp=now().replace("-","").replace(":","").replace(" ","_")
    backup_dir=ROOT/"data"/"backups";backup_dir.mkdir(parents=True,exist_ok=True)
    snapshot=backup_dir/f"fill_form_{stamp}.db";archive=backup_dir/f"fill_form_backup_{stamp}.zip"
    source_db=connect();target_db=sqlite3.connect(snapshot)
    try: source_db.backup(target_db)
    finally: target_db.close();source_db.close()
    try:
        with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
            z.write(snapshot,"history/fill_form.db")
            for path in SOURCE.rglob("*"):
                if path.is_file() and path.suffix.lower() in {".json",".csv"}: z.write(path,Path("source")/path.relative_to(SOURCE))
            archive_dir=ROOT/"data"/"archive"
            for path in archive_dir.glob("*.jsonl") if archive_dir.exists() else []: z.write(path,Path("archive")/path.name)
    finally:
        snapshot.unlink(missing_ok=True)
    return archive

def dashboard(period):
    db=connect(); forms=[]
    for f in db.execute("SELECT * FROM forms WHERE active=1 ORDER BY rowid"):
        c=db.execute("SELECT COUNT(*) FROM submissions WHERE period=? AND form_id=? AND status='success' AND dry_run=0",(period,f["id"])).fetchone()[0]
        failed=db.execute("SELECT COUNT(*) FROM submissions WHERE period=? AND form_id=? AND status='failed'",(period,f["id"])).fetchone()[0]
        forms.append({**dict(f),"success_count":c,"failed_count":failed,"active":bool(f["active"])})
    success=sum(x["success_count"] for x in forms);failed=sum(x["failed_count"] for x in forms)
    staff_used=db.execute("SELECT COUNT(DISTINCT name) FROM submissions WHERE period=? AND status='success' AND dry_run=0",(period,)).fetchone()[0]
    recent=[dict(r) for r in db.execute("SELECT id,submitted_at,form_title,name,degree,department,score_percent,status,error FROM submissions WHERE period=? AND dry_run=0 ORDER BY id DESC LIMIT 500",(period,))]
    staff=[dict(r) for r in db.execute("""SELECT s.id,s.name,s.degree,s.department,s.active,
        COUNT(CASE WHEN sub.status='success' AND sub.dry_run=0 THEN 1 END) AS usage_count
        FROM staff s LEFT JOIN submissions sub ON sub.name=s.name AND sub.degree=s.degree AND sub.department=s.department AND sub.period=?
        GROUP BY s.id ORDER BY s.department,s.degree,s.name""",(period,))]
    for row in staff: row["active"]=bool(row["active"])
    job=db.execute("SELECT id,status,done,total,message FROM jobs ORDER BY id DESC LIMIT 1").fetchone()
    list_cfg=json.loads((SOURCE/"staff_lists.json").read_text(encoding="utf-8"))
    departments=[]
    for list_id,item in list_cfg.items():
        names=list(item.get("departments",[]));count=db.execute(f"SELECT COUNT(*) FROM staff WHERE active=1 AND department IN ({','.join('?' for _ in names)})",names).fetchone()[0] if names else 0
        departments.append({"id":list_id,"title":item.get("title",list_id),"departments":names,"staff_count":count,"default":list_id=="ctch"})
    storage={
        "record_count":db.execute("SELECT COUNT(*) FROM submissions WHERE dry_run=0").fetchone()[0],
        "month_count":db.execute("SELECT COUNT(DISTINCT period) FROM submissions WHERE dry_run=0").fetchone()[0],
        "period_count":db.execute("SELECT COUNT(*) FROM submissions WHERE period=? AND dry_run=0",(period,)).fetchone()[0],
    }
    monthly_history=[]
    for plan in db.execute("SELECT p.period,p.form_id,p.target,f.title FROM monthly_plans p JOIN forms f ON f.id=p.form_id ORDER BY p.period DESC"):
        count=db.execute("SELECT COUNT(*) FROM submissions WHERE period=? AND form_id=? AND status='success' AND dry_run=0",(plan["period"],plan["form_id"])).fetchone()[0]
        departments_used=[row[0] for row in db.execute("SELECT DISTINCT department FROM submissions WHERE period=? AND form_id=? AND status='success' AND dry_run=0 AND department IS NOT NULL ORDER BY department",(plan["period"],plan["form_id"]))]
        monthly_history.append({**dict(plan),"success_count":count,"departments":departments_used,"status":"completed" if count>=plan["target"] else "in_progress" if count else "planned"})
    current_plan=next((row for row in monthly_history if row["period"]==period),None)
    result={"period":period,"totals":{"success":success,"failed":failed,"forms_done":sum(x["success_count"]>=x["monthly_target"] for x in forms),"forms_total":len(forms),"staff_used":staff_used},"forms":forms,"recent":recent,"staff":staff,"departments":departments,"storage":storage,"current_plan":current_plan,"monthly_history":monthly_history,"settings":settings_info(),"job":dict(job) if job else None}
    db.close();return result

def export_csv(period,department=""):
    db=connect();where=["dry_run=0"];params=[]
    if period and period!="all": where.append("period=?");params.append(period)
    if department: where.append("department=?");params.append(department)
    rows=db.execute(f"SELECT * FROM submissions WHERE {' AND '.join(where)} ORDER BY submitted_at,id",params).fetchall()
    output=io.StringIO(newline="");writer=csv.writer(output)
    writer.writerow(["Mã bản ghi","Tháng","Thời gian","Mã biểu mẫu","Tên biểu mẫu","Họ tên","Trình độ","Khoa","Danh sách","Dòng dữ liệu","Tổng điểm","Điểm tối đa","Tỷ lệ (%)","Chi tiết điểm","Nhận xét","Trạng thái","Lỗi","Khóa chống trùng","Dữ liệu gốc JSON"])
    for row in rows:
        writer.writerow([row["id"],row["period"],row["submitted_at"],row["form_id"],row["form_title"],row["name"],row["degree"],row["department"],row["list_id"],row["row_index"],row["score_total"],row["score_max"],row["score_percent"],row["scores"],row["comment"],row["status"],row["error"],row["submission_key"],row["record_json"]])
    db.close();return ('\ufeff'+output.getvalue()).encode('utf-8')

class Handler(BaseHTTPRequestHandler):
    def send_json(self,obj,status=200):
        raw=json.dumps(obj,ensure_ascii=False).encode();self.send_response(status);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Access-Control-Allow-Origin","*");self.send_header("Access-Control-Allow-Headers","Content-Type");self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_OPTIONS(self): self.send_json({})
    def send_bytes(self,raw,content_type,filename):
        self.send_response(200);self.send_header("Content-Type",content_type);self.send_header("Content-Disposition",f'attachment; filename="{filename}"');self.send_header("Access-Control-Allow-Origin","*");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        u=urlparse(self.path)
        if u.path=="/api/dashboard": return self.send_json(dashboard(parse_qs(u.query).get("period",[now()[:7]])[0]))
        if u.path=="/api/export.csv":
            query=parse_qs(u.query);period=query.get("period",[now()[:7]])[0];department=query.get("department",[""])[0]
            return self.send_bytes(export_csv(period,department),"text/csv; charset=utf-8",f"du_lieu_danh_gia_{period}.csv")
        if u.path=="/api/health": return self.send_json({"ok":True})
        self.send_json({"detail":"Không tìm thấy"},404)
    def do_POST(self):
        u=urlparse(self.path);length=int(self.headers.get("Content-Length",0));body=json.loads(self.rfile.read(length) or b"{}")
        db=connect()
        if u.path=="/api/jobs":
            active=db.execute("SELECT id FROM jobs WHERE status IN ('queued','running','stopping') LIMIT 1").fetchone()
            if active: db.close();return self.send_json({"detail":"Đang có một tác vụ khác chạy"},409)
            form_ids=body.get("form_ids",[])
            if len(form_ids)!=1: db.close();return self.send_json({"detail":"Mỗi tháng chỉ được chọn một biểu mẫu"},400)
            valid_lists=set(json.loads((SOURCE/"staff_lists.json").read_text(encoding="utf-8")))
            selected=["ctch"]+[x for x in body.get("list_ids",[]) if x in valid_lists and x!="ctch"]
            period=body.get("period",now()[:7]);count=30;form_id=form_ids[0]
            form=db.execute("SELECT monthly_target FROM forms WHERE id=? AND active=1",(form_id,)).fetchone()
            if not form: db.close();return self.send_json({"detail":"Biểu mẫu không tồn tại hoặc đã tắt"},404)
            existing=db.execute("SELECT form_id FROM monthly_plans WHERE period=?",(period,)).fetchone()
            if existing and existing["form_id"]!=form_id:
                used=db.execute("SELECT COUNT(*) FROM submissions WHERE period=? AND form_id=? AND status='success' AND dry_run=0",(period,existing["form_id"])).fetchone()[0]
                if used: db.close();return self.send_json({"detail":"Tháng này đã bắt đầu một biểu mẫu khác nên không thể đổi"},409)
            current=db.execute("SELECT COUNT(*) FROM submissions WHERE period=? AND form_id=? AND status='success' AND dry_run=0",(period,form_id)).fetchone()[0]
            total=max(0,int(form["monthly_target"])-current)
            if not bool(body.get("dry_run",False)):
                db.execute("INSERT INTO monthly_plans(period,form_id,target,selected_list_ids,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(period) DO UPDATE SET form_id=excluded.form_id,selected_list_ids=excluded.selected_list_ids,updated_at=excluded.updated_at",(period,form_id,int(form["monthly_target"]),json.dumps(selected),now(),now()))
            cur=db.execute("INSERT INTO jobs(period,form_ids,requested_count,dry_run,status,total,message,created_at,selected_list_ids) VALUES(?,?,?,?,?,?,?,?,?)",(period,json.dumps(form_ids),count,int(bool(body.get("dry_run",False))),"queued",total,"Đang chuẩn bị dữ liệu ngẫu nhiên",now(),json.dumps(selected)));job_id=cur.lastrowid;db.commit();db.close()
            subprocess.Popen([sys.executable,str(ROOT/"worker.py"),str(job_id)],cwd=ROOT,stdout=open(ROOT/"data"/"worker.log","a",encoding="utf-8"),stderr=subprocess.STDOUT)
            return self.send_json({"id":job_id,"status":"queued"},201)
        if u.path=="/api/jobs/stop":
            db.execute("UPDATE jobs SET stop_requested=1,status='stopping',message='Sẽ dừng sau lượt hiện tại' WHERE status IN ('queued','running')");db.commit();db.close();return self.send_json({"ok":True})
        if u.path=="/api/staff/toggle":
            staff_id=int(body.get("id",0));active=int(bool(body.get("active")))
            if not db.execute("SELECT 1 FROM staff WHERE id=?",(staff_id,)).fetchone(): db.close();return self.send_json({"detail":"Không tìm thấy nhân sự"},404)
            db.execute("UPDATE staff SET active=? WHERE id=?",(active,staff_id));db.commit();db.close();return self.send_json({"ok":True})
        if u.path=="/api/settings/open-login":
            db.close()
            subprocess.Popen([sys.executable,str(ROOT/"login_browser.py")],cwd=ROOT,stdout=open(ROOT/"data"/"login.log","a",encoding="utf-8"),stderr=subprocess.STDOUT)
            return self.send_json({"ok":True})
        if u.path=="/api/settings/backup":
            db.close();path=create_backup();return self.send_json({"ok":True,"path":str(path)})
        db.close();self.send_json({"detail":"Không tìm thấy"},404)
    def log_message(self,fmt,*args): pass

if __name__=="__main__":
    init_db();print("Dịch vụ: http://127.0.0.1:8765");ThreadingHTTPServer(("127.0.0.1",8765),Handler).serve_forever()

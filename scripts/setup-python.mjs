import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import process from "node:process";

const root=process.cwd(), app=join(root,"local_app"), isWin=process.platform==="win32";
const base=isWin?{command:"py",args:["-3"]}:{command:"python3",args:[]};
const venv=join(app,".venv",isWin?"Scripts/python.exe":"bin/python");
if(!existsSync(venv)){
  const r=spawnSync(base.command,[...base.args,"-m","venv",join(app,".venv")],{stdio:"inherit"});
  if(r.status!==0)process.exit(r.status??1);
}
for(const args of [["-m","pip","install","-r",join(app,"requirements.txt")],["-m","playwright","install","chromium"]]){
  const r=spawnSync(venv,args,{stdio:"inherit"});if(r.status!==0)process.exit(r.status??1);
}
console.log("\nDa cai xong Python, Playwright va Chromium.\n");

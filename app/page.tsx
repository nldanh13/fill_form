"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, Archive, CalendarCheck, CalendarRange, Database, Download, FileSpreadsheet, HardDriveDownload, LogIn, Play, Search, Settings, ShieldCheck, Shuffle, Square, Stethoscope } from "lucide-react";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast, Toaster } from "sonner";

type FormRow={id:string;title:string;question_count:number;monthly_target:number;success_count:number;failed_count:number;active:boolean};
type HistoryRow={id:number;submitted_at:string;form_title:string;name:string;degree:string;department:string;score_percent:number;status:string;error?:string};
type StaffRow={id:number;name:string;degree:string;department:string;active:boolean;usage_count:number};
type DepartmentRow={id:string;title:string;departments:string[];staff_count:number;default:boolean};
type MonthlyPlan={period:string;form_id:string;title:string;target:number;success_count:number;departments:string[];status:"planned"|"in_progress"|"completed"};
type Dashboard={
  period:string;
  totals:{success:number;failed:number;forms_done:number;forms_total:number;staff_used:number};
  forms:FormRow[];
  recent:HistoryRow[];
  staff:StaffRow[];
  departments:DepartmentRow[];
  storage:{record_count:number;month_count:number;period_count:number};
  current_plan:MonthlyPlan|null;
  monthly_history:MonthlyPlan[];
  settings:{email:string;browser_profile_exists:boolean;backup_dir:string};
  job?:{id:number;status:string;done:number;total:number;message:string}|null;
};

const FORM_SEED=[
  ["form_glucose","Đánh giá đường máu mao mạch",14],
  ["form_tiem_ngoai_th","Bảng kiểm tiêm tĩnh mạch",17],
  ["form_vet_thuong_sach","Đánh giá chăm sóc vết thương sạch",24],
  ["form_tiem_bap_trong_da_duoi_da","Đánh giá tiêm bắp / tiêm trong da / tiêm dưới da",15],
  ["form_bo_bot","Bảng kiểm kỹ thuật bó bột",13],
  ["form_cat_chi","Bảng kiểm kỹ thuật cắt chỉ vết thương",25],
  ["form_catheter_ngoai_vi","Bảng kiểm tiêm hoặc truyền dịch qua catheter ngoại vi",14],
  ["form_loet_ty_de","Bảng kiểm chăm sóc vết loét tỳ đè",21],
  ["form_vet_thuong_nhiem_khuan","Bảng kiểm chăm sóc vết thương nhiễm khuẩn",25],
] as const;
const currentPeriod=()=>new Date().toISOString().slice(0,7);
const sample:Dashboard={
  period:currentPeriod(),totals:{success:0,failed:0,forms_done:0,forms_total:9,staff_used:0},
  forms:FORM_SEED.map(([id,title,question_count])=>({id,title,question_count,monthly_target:30,success_count:0,failed_count:0,active:true})),
  recent:[],staff:[],departments:[{id:"ctch",title:"Khoa CTCH",departments:["CTCH"],staff_count:0,default:true}],storage:{record_count:0,month_count:0,period_count:0},current_plan:null,monthly_history:[],settings:{email:"",browser_profile_exists:false,backup_dir:""},job:null,
};

async function api<T>(path:string,init?:RequestInit):Promise<T>{
  const response=await fetch(`http://127.0.0.1:8765/api${path}`,{...init,headers:{"Content-Type":"application/json",...(init?.headers||{})}});
  if(!response.ok){const error=await response.json().catch(()=>({detail:"Lỗi dịch vụ"}));throw new Error(error.detail)}
  return response.json();
}
const panel="border-slate-200 bg-white text-slate-950 shadow-[0_1px_2px_rgba(15,23,42,.05)]";
const monthLabel=(period:string)=>new Intl.DateTimeFormat("vi-VN",{month:"long",year:"numeric"}).format(new Date(`${period}-01T00:00:00`));

export default function Home(){
  const [tab,setTab]=useState("month");
  const [period,setPeriod]=useState(currentPeriod());
  const [data,setData]=useState(sample);
  const [online,setOnline]=useState(false);
  const [chosenForm,setChosenForm]=useState("");
  const [selectedLists,setSelectedLists]=useState<string[]>(["ctch"]);
  const [query,setQuery]=useState("");
  const [staffQuery,setStaffQuery]=useState("");
  const [departmentFilter,setDepartmentFilter]=useState("all");

  const load=useCallback(async()=>{try{const next=await api<Dashboard>(`/dashboard?period=${period}`);setData(next);setChosenForm(current=>next.current_plan?.form_id||current);setOnline(true)}catch{setOnline(false)}},[period]);
  useEffect(()=>{const first=setTimeout(()=>void load(),0);const timer=setInterval(()=>void load(),3000);return()=>{clearTimeout(first);clearInterval(timer)}},[load]);

  const selectedForm=data.forms.find(form=>form.id===chosenForm);
  const remaining=selectedForm?Math.max(0,selectedForm.monthly_target-selectedForm.success_count):0;
  const filteredHistory=useMemo(()=>data.recent.filter(row=>(departmentFilter==="all"||row.department===departmentFilter)&&`${row.form_title} ${row.name} ${row.department}`.toLowerCase().includes(query.toLowerCase())),[data.recent,departmentFilter,query]);
  const filteredStaff=useMemo(()=>data.staff.filter(row=>`${row.name} ${row.degree} ${row.department}`.toLowerCase().includes(staffQuery.toLowerCase())),[data.staff,staffQuery]);

  async function start(dryRun:boolean){
    if(!chosenForm)return toast.error("Hãy chọn một biểu mẫu cho tháng này");
    if(!remaining&&!dryRun)return toast.success("Biểu mẫu tháng này đã đủ 30 lượt");
    try{await api("/jobs",{method:"POST",body:JSON.stringify({period,form_ids:[chosenForm],list_ids:selectedLists,dry_run:dryRun})});toast.success(dryRun?"Đã bắt đầu chạy thử":"Đã bắt đầu điền đủ 30 lượt");if(!dryRun)setTab("month");void load()}catch(error){toast.error(error instanceof Error?error.message:"Không thể bắt đầu")}
  }
  async function stop(){try{await api("/jobs/stop",{method:"POST"});toast.success("Sẽ dừng sau lượt hiện tại")}catch(error){toast.error(error instanceof Error?error.message:"Không thể dừng")}}
  async function toggleStaff(row:StaffRow,active:boolean){try{await api("/staff/toggle",{method:"POST",body:JSON.stringify({id:row.id,active})});toast.success(active?`Đã dùng lại ${row.name}`:`Đã tạm ngưng ${row.name}`);void load()}catch(error){toast.error(error instanceof Error?error.message:"Không thể cập nhật")}}
  async function openLogin(){try{await api("/settings/open-login",{method:"POST"});toast.success("Đã mở Google. Đăng nhập xong, bạn hãy đóng cửa sổ đó.")}catch(error){toast.error(error instanceof Error?error.message:"Không thể mở Google")}}
  async function backup(){try{const result=await api<{path:string}>("/settings/backup",{method:"POST"});toast.success(`Đã sao lưu tại: ${result.path}`,{duration:8000});void load()}catch(error){toast.error(error instanceof Error?error.message:"Không thể sao lưu")}}
  function toggleList(id:string){if(id==="ctch")return;setSelectedLists(items=>items.includes(id)?items.filter(item=>item!==id):[...items,id])}
  function exportCsv(){const department=departmentFilter==="all"?"":`&department=${encodeURIComponent(departmentFilter)}`;window.location.href=`http://127.0.0.1:8765/api/export.csv?period=${period}${department}`}

  const activeJob=data.job&&["queued","running","stopping"].includes(data.job.status)?data.job:null;
  const lockedFormId=data.current_plan&&data.current_plan.success_count>0?data.current_plan.form_id:"";
  const titles:Record<string,string>={month:"Kế hoạch tháng",run:"Chọn biểu mẫu tháng",data:"Kho dữ liệu",settings:"Thiết lập"};
  const navigation=[["month",CalendarCheck,"Tháng này"],["run",Shuffle,"Chọn biểu mẫu"],["data",Database,"Kho dữ liệu"],["settings",Settings,"Thiết lập"]] as const;

  return <main className="min-h-screen bg-[#f5f8f7] text-slate-950"><Toaster richColors position="top-right"/><div className="mx-auto grid min-h-screen max-w-[1640px] lg:grid-cols-[232px_1fr]">
    <aside className="bg-[#063c3a] px-4 py-6 text-white"><div className="mb-9 flex items-center gap-3 px-2"><div className="rounded-xl bg-[#c8f34a] p-2 text-[#063c3a]"><Stethoscope/></div><div><b className="block">Trợ lý điền phiếu</b><small className="text-teal-100/60">Ngoại CTCH – TK</small></div></div><nav className="grid gap-1 sm:grid-cols-4 lg:grid-cols-1">{navigation.map(([id,Icon,label])=><button key={id} onClick={()=>{setTab(id);setQuery("")}} className={`flex items-center gap-3 rounded-xl px-3 py-3 text-sm transition ${tab===id?"bg-white font-medium text-[#063c3a] shadow-sm":"text-teal-50/75 hover:bg-white/10 hover:text-white"}`}><Icon size={18}/>{label}</button>)}</nav><div className="mt-10 rounded-xl border border-white/10 bg-white/5 p-3 text-xs"><div><span className={`mr-2 inline-block h-2 w-2 rounded-full ${online?"bg-[#c8f34a]":"bg-amber-400"}`}/>{online?"Đã kết nối":"Đang xem dữ liệu mẫu"}</div><p className="mt-2 leading-5 text-teal-100/55">Mỗi tháng chọn một biểu mẫu và lưu đủ 30 kết quả.</p></div></aside>
    <section className="min-w-0 px-5 py-6 md:px-8 lg:px-10"><header className="mb-7 flex flex-wrap items-center justify-between gap-4"><div><p className="text-xs font-bold tracking-[.14em] text-teal-700">ĐÁNH GIÁ KỸ THUẬT ĐIỀU DƯỠNG</p><h1 className="mt-1 text-3xl font-bold tracking-tight">{titles[tab]}</h1></div><label className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-sm"><CalendarRange size={17}/><Input type="month" value={period} onChange={event=>{setPeriod(event.target.value);setChosenForm("")}} className="h-7 w-36 border-0 p-0 shadow-none"/></label></header>

    {activeJob&&<Card className="mb-5 border-teal-200 bg-teal-50 text-slate-950"><CardContent className="flex flex-wrap items-center gap-4 p-4"><div className="rounded-full bg-teal-100 p-2 text-teal-700"><Activity className="animate-pulse" size={18}/></div><div className="min-w-48 flex-1"><b>Đang thực hiện</b><p className="text-sm text-slate-600">{activeJob.message}</p><Progress className="mt-2" value={activeJob.total?activeJob.done/activeJob.total*100:0}/></div><Button variant="outline" onClick={stop}><Square size={15}/>Dừng an toàn</Button></CardContent></Card>}

    {tab==="month"&&<div className="space-y-5"><Card className="overflow-hidden border-0 bg-[#073f3b] text-white shadow-sm"><CardContent className="grid gap-6 p-6 md:grid-cols-[1fr_auto] md:items-center"><div><Badge className="mb-4 bg-[#c8f34a] text-[#073f3b] hover:bg-[#c8f34a]">{monthLabel(period)}</Badge>{data.current_plan?<><p className="text-sm font-medium text-teal-50/65">BIỂU MẪU ĐÃ CHỌN TRONG THÁNG</p><h2 className="mt-2 max-w-3xl text-2xl font-bold">{data.current_plan.title}</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-teal-50/70">Hệ thống chỉ điền biểu mẫu này, chọn ngẫu nhiên nhân sự CTCH và tự dừng khi đủ 30 lượt.</p></>:<><h2 className="text-2xl font-bold">Tháng này chưa chọn biểu mẫu</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-teal-50/70">Chọn một trong 9 biểu mẫu, sau đó hệ thống sẽ điền đủ 30 lượt và ghi lại vào lịch sử tháng.</p></>}<Button onClick={()=>setTab("run")} className="mt-5 bg-white text-[#073f3b] hover:bg-teal-50"><Shuffle size={17}/>{data.current_plan?"Tiếp tục điền":"Chọn biểu mẫu tháng này"}</Button></div><div className="min-w-48 rounded-2xl border border-white/10 bg-white/10 p-5"><p className="text-sm text-teal-50/65">Tiến độ tháng</p><p className="mt-1 text-4xl font-bold">{data.current_plan?.success_count||0}<span className="text-lg font-normal text-teal-50/55">/30</span></p><Progress className="my-3 bg-white/15" value={(data.current_plan?.success_count||0)/30*100}/><p className="text-sm">{data.current_plan?.status==="completed"?"Đã hoàn thành":"Còn "+(30-(data.current_plan?.success_count||0))+" lượt"}</p></div></CardContent></Card>
      <Card className={panel}><CardHeader><CardTitle>Danh sách biểu mẫu đã điền theo tháng</CardTitle><p className="text-sm text-slate-500">Mỗi tháng một dòng, giúp bạn biết tháng nào đã sử dụng biểu mẫu nào.</p></CardHeader><CardContent><Table><TableHeader><TableRow><TableHead>Tháng</TableHead><TableHead>Biểu mẫu đã chọn</TableHead><TableHead>Khoa đã dùng</TableHead><TableHead>Tiến độ</TableHead><TableHead>Trạng thái</TableHead></TableRow></TableHeader><TableBody>{data.monthly_history.length?data.monthly_history.map(plan=><TableRow key={plan.period} className={plan.period===period?"bg-teal-50/50":""}><TableCell className="font-medium capitalize">{monthLabel(plan.period)}</TableCell><TableCell className="font-medium">{plan.title}</TableCell><TableCell>{plan.departments.length?plan.departments.join(", "):"Chưa có dữ liệu"}</TableCell><TableCell><div className="flex min-w-40 items-center gap-3"><Progress value={Math.min(100,plan.success_count/plan.target*100)}/><b className="whitespace-nowrap">{plan.success_count}/{plan.target}</b></div></TableCell><TableCell><PlanBadge status={plan.status}/></TableCell></TableRow>):<TableRow><TableCell colSpan={5} className="h-32 text-center text-slate-500">Chưa có tháng nào được ghi nhận.</TableCell></TableRow>}</TableBody></Table></CardContent></Card>
    </div>}

    {tab==="run"&&<div className="grid gap-5 xl:grid-cols-[1fr_380px]"><div className="space-y-5"><Card className={panel}><CardHeader><CardTitle>1. Chọn một biểu mẫu</CardTitle><p className="text-sm text-slate-500">Mỗi tháng chỉ chọn một biểu mẫu để điền đủ 30 lượt.</p>{lockedFormId&&<p className="mt-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Tháng này đã có dữ liệu nên biểu mẫu đã được khóa, không thể đổi sang biểu mẫu khác.</p>}</CardHeader><CardContent><RadioGroup value={chosenForm} onValueChange={setChosenForm} className="grid gap-3 md:grid-cols-2">{data.forms.map(form=>{const selected=chosenForm===form.id;const disabled=Boolean(lockedFormId&&lockedFormId!==form.id);return <label key={form.id} className={`flex gap-3 rounded-xl border p-4 ${disabled?"cursor-not-allowed bg-slate-50 opacity-50":"cursor-pointer"} ${selected?"border-teal-500 bg-teal-50/70":"border-slate-200 hover:border-slate-300"}`}><RadioGroupItem value={form.id} disabled={disabled} className="mt-0.5 border-teal-600 text-teal-700"/><div><b className="block leading-5">{form.title}</b><span className="mt-1 block text-sm text-slate-500">{form.question_count} câu · {form.success_count}/30 lượt trong tháng</span></div></label>})}</RadioGroup></CardContent></Card>
      <Card className={panel}><CardHeader><CardTitle>2. Chọn khoa</CardTitle><p className="text-sm text-slate-500">CTCH luôn là nguồn chính. Chỉ tích thêm khoa khác khi thật sự cần.</p></CardHeader><CardContent className="grid gap-3 md:grid-cols-3">{data.departments.map(item=>{const checked=selectedLists.includes(item.id);return <label key={item.id} className={`flex items-start gap-3 rounded-xl border p-4 ${checked?"border-teal-500 bg-teal-50/70":"border-slate-200"}`}><Checkbox checked={checked} disabled={item.id==="ctch"} onCheckedChange={()=>toggleList(item.id)}/><span><b className="block">{item.departments.join(", ")}</b><small className="text-slate-500">{item.staff_count} nhân sự{item.id==="ctch"?" · mặc định":""}</small></span></label>})}</CardContent></Card></div>
      <Card className={`${panel} h-fit xl:sticky xl:top-6`}><CardHeader><CardTitle>Kế hoạch tháng</CardTitle></CardHeader><CardContent className="space-y-5"><div className="rounded-xl bg-slate-50 p-4"><SummaryRow label="Tháng" value={monthLabel(period)}/><SummaryRow label="Biểu mẫu" value={selectedForm?.title||"Chưa chọn"}/><SummaryRow label="Đã có" value={`${selectedForm?.success_count||0}/30 lượt`}/><SummaryRow label="Cần điền thêm" value={`${remaining} lượt`}/><SummaryRow label="Nguồn nhân sự" value={data.departments.filter(item=>selectedLists.includes(item.id)).flatMap(item=>item.departments).join(", ")}/></div><div className="flex gap-3 rounded-xl border border-teal-100 bg-teal-50 p-3 text-sm text-teal-900"><Shuffle className="mt-0.5 shrink-0" size={18}/><p>Chỉ biểu mẫu đã chọn được chạy. Dữ liệu được chọn ngẫu nhiên, chia đều nhân sự và chống trùng trong tháng.</p></div><Button className="h-11 w-full bg-[#0b746b] hover:bg-[#095f58]" onClick={()=>void start(false)} disabled={!chosenForm}><Play size={17}/>Điền đủ 30 lượt</Button><Button variant="outline" className="w-full" onClick={()=>void start(true)} disabled={!chosenForm}>Chạy thử, không gửi form</Button></CardContent></Card>
    </div>}

    {tab==="data"&&<div className="space-y-5"><Card className={panel}><CardHeader className="gap-4 lg:flex-row lg:items-center lg:justify-between"><div><CardTitle className="flex items-center gap-2"><Database className="text-teal-700"/>Dữ liệu {monthLabel(period)}</CardTitle><p className="mt-1 text-sm text-slate-500">{data.storage.period_count} bản ghi trong tháng · {data.storage.record_count} bản ghi đang được lưu lâu dài</p></div><div className="flex flex-wrap gap-2"><Button variant="outline" onClick={exportCsv}><FileSpreadsheet size={17}/>Xuất CSV mở bằng Excel</Button><Button variant="outline" onClick={backup}><Archive size={17}/>Sao lưu toàn bộ</Button></div></CardHeader><CardContent><div className="mb-4 flex flex-wrap gap-3"><SearchBox query={query} setQuery={setQuery}/><Select value={departmentFilter} onValueChange={setDepartmentFilter}><SelectTrigger className="w-52 bg-white"><SelectValue placeholder="Tất cả khoa"/></SelectTrigger><SelectContent><SelectItem value="all">Tất cả khoa</SelectItem>{[...new Set(data.staff.map(row=>row.department))].map(department=><SelectItem key={department} value={department}>{department}</SelectItem>)}</SelectContent></Select></div><div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>Thời gian</TableHead><TableHead>Biểu mẫu</TableHead><TableHead>Người được đánh giá</TableHead><TableHead>Khoa</TableHead><TableHead>Điểm</TableHead><TableHead>Trạng thái</TableHead></TableRow></TableHeader><TableBody>{filteredHistory.length?filteredHistory.map(row=><TableRow key={row.id}><TableCell className="whitespace-nowrap">{row.submitted_at}</TableCell><TableCell className="min-w-64 font-medium">{row.form_title}</TableCell><TableCell className="whitespace-nowrap">{row.name}<small className="block text-slate-500">{row.degree}</small></TableCell><TableCell>{row.department}</TableCell><TableCell>{row.score_percent?.toFixed(1)}%</TableCell><TableCell><Badge className={row.status==="success"?"bg-emerald-100 text-emerald-800":"bg-rose-100 text-rose-800"}>{row.status==="success"?"Đã gửi":"Lỗi"}</Badge></TableCell></TableRow>):<TableRow><TableCell colSpan={6} className="h-32 text-center text-slate-500">Chưa có dữ liệu phù hợp.</TableCell></TableRow>}</TableBody></Table></div></CardContent></Card>
      <Card className="border-teal-100 bg-teal-50/60 text-slate-950"><CardContent className="grid gap-4 p-5 md:grid-cols-3"><StorageNote title="Google Form" text="Vẫn lưu câu trả lời theo cấu hình Google Sheet hiện tại."/><StorageNote title="Cơ sở dữ liệu" text="Lưu có cấu trúc để tìm theo tháng, form, khoa và nhân sự."/><StorageNote title="Tệp dữ liệu mở" text="Tự ghi thêm JSONL và có thể xuất CSV để dùng lâu dài."/></CardContent></Card>
    </div>}

    {tab==="settings"&&<div className="space-y-5"><div className="grid gap-5 md:grid-cols-2"><Card className={panel}><CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="text-teal-700"/>Phiên Google</CardTitle></CardHeader><CardContent className="space-y-4"><div className="rounded-xl bg-slate-50 p-4"><p className="text-sm text-slate-500">Tài khoản cấu hình</p><p className="font-medium">{data.settings.email||"Chưa cấu hình"}</p><p className="mt-2 text-sm">{data.settings.browser_profile_exists?"Đã có hồ sơ đăng nhập":"Chưa tạo hồ sơ đăng nhập"}</p></div><Button onClick={openLogin} className="bg-[#0b746b] hover:bg-[#095f58]"><LogIn size={17}/>Mở đăng nhập Google</Button></CardContent></Card><Card className={panel}><CardHeader><CardTitle className="flex items-center gap-2"><HardDriveDownload className="text-teal-700"/>An toàn dữ liệu</CardTitle></CardHeader><CardContent className="space-y-4"><p className="text-sm leading-6 text-slate-600">Bản sao lưu gồm lịch sử, dữ liệu mở, cấu hình form và danh sách nhân sự; không chứa cookie Google.</p><p className="break-all rounded-xl bg-slate-50 p-3 text-xs">{data.settings.backup_dir||"local_app/data/backups"}</p><Button variant="outline" onClick={backup}><Download size={17}/>Tạo bản sao lưu</Button></CardContent></Card></div>
      <Card className={panel}><CardContent className="px-6"><Accordion type="multiple"><AccordionItem value="forms"><AccordionTrigger className="text-base">Danh mục {data.forms.length} biểu mẫu</AccordionTrigger><AccordionContent><div className="grid gap-2 md:grid-cols-2">{data.forms.map(form=><div key={form.id} className="flex items-center justify-between rounded-lg border p-3"><div><b>{form.title}</b><small className="block text-slate-500">{form.question_count} câu</small></div><Badge variant="outline">Có thể chọn</Badge></div>)}</div></AccordionContent></AccordionItem><AccordionItem value="staff"><AccordionTrigger className="text-base">Quản lý nhân sự ({data.staff.filter(row=>row.active).length}/{data.staff.length} đang dùng)</AccordionTrigger><AccordionContent><div className="mb-3"><SearchBox query={staffQuery} setQuery={setStaffQuery}/></div><div className="max-h-[480px] overflow-auto"><Table><TableHeader><TableRow><TableHead>Họ tên</TableHead><TableHead>Trình độ</TableHead><TableHead>Khoa</TableHead><TableHead className="text-right">Sử dụng</TableHead></TableRow></TableHeader><TableBody>{filteredStaff.map(row=><TableRow key={row.id}><TableCell className="font-medium">{row.name}</TableCell><TableCell>{row.degree}</TableCell><TableCell>{row.department}</TableCell><TableCell className="text-right"><Switch checked={row.active} onCheckedChange={active=>void toggleStaff(row,active)} className="data-[state=checked]:bg-[#0b746b]"/></TableCell></TableRow>)}</TableBody></Table></div></AccordionContent></AccordionItem></Accordion></CardContent></Card>
    </div>}
    </section></div></main>
}

function SearchBox({query,setQuery}:{query:string;setQuery:(value:string)=>void}){return <div className="relative"><Search className="absolute left-3 top-2.5 text-slate-400" size={17}/><Input value={query} onChange={event=>setQuery(event.target.value)} placeholder="Tìm kiếm..." className="w-64 bg-white pl-9"/></div>}
function SummaryRow({label,value}:{label:string;value:string}){return <div className="flex items-start justify-between gap-4 border-b border-slate-200 py-2 last:border-0"><span className="text-sm text-slate-500">{label}</span><b className="max-w-52 text-right text-sm">{value}</b></div>}
function StorageNote({title,text}:{title:string;text:string}){return <div className="flex gap-3"><div className="mt-1 h-2 w-2 shrink-0 rounded-full bg-teal-600"/><div><b>{title}</b><p className="mt-1 text-sm leading-5 text-slate-600">{text}</p></div></div>}
function PlanBadge({status}:{status:MonthlyPlan["status"]}){if(status==="completed")return <Badge className="bg-emerald-100 text-emerald-800">Đã đủ 30</Badge>;if(status==="in_progress")return <Badge className="bg-amber-100 text-amber-800">Đang thực hiện</Badge>;return <Badge variant="outline">Đã chọn</Badge>}

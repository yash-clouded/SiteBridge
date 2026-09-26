"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

export type WorkstationRole =
  | "CLIENT"
  | "PROJECT MANAGER"
  | "CONTRACTOR"
  | "SITE ENGINEER"
  | "SITE OPERATIVES"
  | "PLANNER / PROJECT CONTROLS"
  | "DISCIPLINE ENGINEER";

const ROLES: WorkstationRole[] = [
  "CLIENT",
  "PROJECT MANAGER",
  "CONTRACTOR",
  "SITE ENGINEER",
  "SITE OPERATIVES",
  "PLANNER / PROJECT CONTROLS",
  "DISCIPLINE ENGINEER",
];

const workPackages = [
  {
    name: "Area B Compressor Foundation Concrete Work",
    code: "CONCRETE-01",
    progress: 88.5,
    float: "14 Days Extra Time in Hand",
    finish: "28-SEP-2026",
    tone: "approved" as const,
    engineer: "Er. Rajesh Nath",
    details: "Head Civil Engineer · ID: OIL-ENG-1104",
    channel: "04",
  },
  {
    name: "24″ Process Line Big Pipe Fitting & Welding",
    code: "PIPING-02",
    progress: 74.2,
    float: "4 Days Extra Time in Hand",
    finish: "30-SEP-2026",
    tone: "pending" as const,
    engineer: "Er. Ramesh Sharma",
    details: "Head Piping Engineer · ID: OIL-ENG-4402",
    channel: "02",
  },
  {
    name: "Substation 02 Heavy Cable Tray & Power Line Fitting",
    code: "ELECTRIC-03",
    progress: 62,
    float: "5 Days Extra Time in Hand",
    finish: "05-OCT-2026",
    tone: "pending" as const,
    engineer: "Er. Anup Barman",
    details: "Head Electrical Engineer · ID: OIL-ENG-2219",
    channel: "07",
  },
  {
    name: "Water Pressure & Pipe Leakage Testing",
    code: "LEAKTEST-04",
    progress: 45,
    float: "Only 2 Days Left (Risk of Delay)",
    finish: "02-OCT-2026",
    tone: "rejected" as const,
    engineer: "Er. Kamal Gogoi",
    details: "Head Quality & Testing Engineer · ID: OIL-ENG-3091",
    channel: "01",
  },
];

function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "approved" | "pending" | "rejected" | "blue" | "neutral" }) {
  const classes = {
    approved: "border-[#b6ebc4] bg-[#ebfaef] text-[#086e24]",
    pending: "border-[#ffe199] bg-[#fff8e6] text-[#8f6000]",
    rejected: "border-[#f8b4b4] bg-[#fdf2f2] text-[#9e1a1a]",
    blue: "border-[#bfdbfe] bg-[#eff6ff] text-[#0c4a9e]",
    neutral: "border-slate-300 bg-slate-100 text-slate-700",
  };
  return <span className={"inline-flex items-center rounded-[2px] border px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase " + classes[tone]}>{children}</span>;
}

function ProgressBar({ value, tone = "blue" }: { value: number; tone?: "blue" | "green" | "amber" }) {
  const fill = { blue: "bg-[#0b5ed7]", green: "bg-[#198754]", amber: "bg-[#d97706]" }[tone];
  return <div className="h-3 overflow-hidden rounded-[1px] border border-slate-300 bg-[#e2e7ec]"><div className={"h-full transition-all " + fill} style={{ width: value + "%" }} /></div>;
}

function Panel({ title, subtitle, children, action }: { title: string; subtitle?: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="rounded-[2px] border border-slate-300 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-2.5">
        <div><h2 className="text-xs font-bold uppercase tracking-wide text-slate-900">{title}</h2>{subtitle ? <p className="mt-0.5 text-[11px] text-slate-500">{subtitle}</p> : null}</div>
        {action}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

function ClientWorkspace() {
  const [tab, setTab] = useState<"health" | "finance" | "contacts">("health");
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1 border-b border-slate-300">
        {[
          ["health", "Work Progress"],
          ["finance", "Money & Payments"],
          ["contacts", "Contractor Phone Book"],
        ].map(([key, label]) => (
          <button key={key} onClick={() => setTab(key as "health" | "finance" | "contacts")} className={"rounded-t-[2px] px-3 py-2 text-[11px] font-semibold uppercase tracking-wide " + (tab === key ? "border-x border-t border-slate-300 bg-white text-[#0d6efd]" : "text-slate-500")}>{label}</button>
        ))}
      </div>

      {tab === "health" ? (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-[2px] border border-slate-300 bg-white p-3">
            <div className="flex items-center gap-2"><span className="text-[11px] font-bold text-slate-600">Worker Safety Record:</span><Badge tone="approved">Verified · zero serious accidents</Badge></div>
            <button onClick={() => window.alert("Client summary prepared for export.")} className="rounded-[2px] border border-[#343b49] bg-[#181b22] px-2.5 py-1 text-[11px] font-medium text-slate-100">Download 1-Page Summary</button>
          </div>

          <div className="grid gap-3 md:grid-cols-3">
            <Kpi title="Agreed Promised Finish Date" value="15-Nov-2026" hint="Original contract handover date" />
            <Kpi title="Realistic Expected Finish Date" value="04-Dec-2026" hint="Running 19 days late at current speed" />
            <Kpi title="Work Left To Be Completed" value="22.3%" hint="77.7% confirmed vs 92.0% planned" />
          </div>

          <Panel title="Overall Project Work Completed">
            <div className="mb-1.5 flex items-center justify-between text-xs"><span className="font-bold uppercase">Actually Finished</span><span className="font-mono font-bold text-[#0d6efd]">77.7%</span></div>
            <div className="flex h-[18px] overflow-hidden rounded-[2px] border border-slate-300 bg-[#e2e7ec]">
              <div className="flex items-center justify-center bg-[#0b5ed7] text-[10px] font-bold text-white" style={{ width: "77.7%" }}>77.7% Confirmed Done</div>
              <div className="flex items-center justify-center bg-[#d97706] text-[10px] font-bold text-slate-950" style={{ width: "14.3%" }}>14.3% Gap</div>
            </div>
            <div className="mt-1.5 flex justify-between text-[10px] font-mono text-slate-500"><span>AGREED TARGET TODAY: 92.0%</span><span className="font-bold text-amber-800">BEHIND TARGET: 14.3%</span></div>
          </Panel>

          <Panel title="Progress by Type of Work">
            <div className="space-y-3">
              {[
                ["Ground & Concrete Work", 88.5, "green"],
                ["Pipeline & Mechanical Work", 74.2, "blue"],
                ["Electrical & Power Cabling", 62, "amber"],
                ["Sensors & Automatic Controls", 45, "blue"],
              ].map(([label, value, tone]) => (
                <div key={label as string}>
                  <div className="mb-1 flex justify-between text-xs"><span className="font-semibold text-slate-800">{label}</span><span className="font-mono font-bold text-slate-700">{value}%</span></div>
                  <ProgressBar value={Number(value)} tone={tone as "blue" | "green" | "amber"} />
                </div>
              ))}
            </div>
          </Panel>
        </>
      ) : tab === "finance" ? (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            <Kpi title="Total Approved Project Budget" value="₹420.00 Cr" hint="Total funds sanctioned" />
            <Kpi title="Extra Estimated Cost Due to Delay" value="+₹8.40 Cr" hint="Machine rent, site stay & extra staff" />
            <Kpi title="Money Already Paid Out" value="₹248.50 Cr" hint="Paid for confirmed completed work" />
          </div>
          <Panel title="Upcoming Payment Schedule & Cash Planning">
            <div className="space-y-3">
              {[
                ["Planned bills by this month", "₹284.00 Cr", 67.6, "bg-slate-500"],
                ["Bills verified & actually paid", "₹248.50 Cr", 59.1, "bg-[#198754]"],
                ["Next estimated payment required", "₹35.50 Cr", 8.4, "bg-[#d97706]"],
              ].map(([label, amount, width, cls]) => (
                <div key={label as string}><div className="mb-0.5 flex justify-between text-[11px]"><span>{label}</span><span className="font-mono font-bold">{amount}</span></div><div className="h-3 overflow-hidden bg-slate-200"><div className={"h-full " + cls} style={{ width: Number(width) + "%" }} /></div></div>
              ))}
            </div>
          </Panel>
          <div className="rounded-[2px] border border-blue-200 bg-blue-50 p-3 text-xs text-blue-900"><strong>Money note:</strong> the prototype's advisory layer flags the next payment for review when physical progress trails the plan.</div>
        </>
      ) : (
        <Panel title="Contractor & Company Contact Directory" subtitle="Contact persons in charge of each work package">
          <div className="overflow-x-auto">
            <table className="eng-table w-full min-w-[780px] text-left">
              <thead><tr><th className="px-2.5 py-2">Company</th><th className="px-2.5 py-2">Work</th><th className="px-2.5 py-2">Person</th><th className="px-2.5 py-2">Phone</th><th className="px-2.5 py-2">Office</th></tr></thead>
              <tbody>{[
                ["Apex Infra Projects Ltd", "Civil & Ground Work", "S. K. Patnaik", "+91 98301 44210", "Cabin C-04, Gate 1"],
                ["Bridge & Piping Tech EPC", "Pipeline Laying", "Harish Rawat", "+91 94350 21980", "Bay B Trestle Office"],
                ["PowerGrid Solutions", "Electrical & Wiring", "Alok Sengupta", "+91 98640 11722", "Substation Office"],
              ].map((row) => <tr key={row[0]}>{row.map((v, i) => <td key={i} className={"px-2.5 py-2 " + (i === 0 ? "font-bold text-slate-900" : "text-slate-600")}>{v}</td>)}</tr>)}</tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  );
}

function ProjectManagerWorkspace() {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between rounded-[2px] border border-slate-700 bg-slate-900 px-3.5 py-2 text-xs font-mono text-slate-300"><span>● Ground Weather: Clear (32°C) · Wind low & safe for crane work</span><span className="text-slate-400">Weather Condition: Normal</span></div>
      <Panel title="Current Work Happening on Site" subtitle="Open a work package to see progress and the responsible engineer" action={<Badge>4 active work areas</Badge>}>
        <div className="space-y-2">
          {workPackages.map((wp, index) => (
            <div key={wp.code} className="rounded-[2px] border border-slate-300 bg-white">
              <button onClick={() => setOpen(open === index ? null : index)} className="flex w-full flex-wrap items-center justify-between gap-2 bg-slate-50 px-3 py-2 text-left hover:bg-slate-100">
                <div className="flex items-center gap-2"><span className="font-mono text-xs font-bold text-slate-500">{open === index ? "▼" : "►"}</span><span className="text-xs font-bold text-slate-900">{wp.name}</span><span className="font-mono text-[10px] text-slate-500">[{wp.code}]</span></div>
                <div className="flex flex-wrap items-center gap-2"><Badge tone={wp.tone}>{wp.float}</Badge><Badge tone={wp.progress >= 80 ? "approved" : wp.progress < 50 ? "rejected" : "blue"}>{wp.progress}% FINISHED</Badge><span className="font-mono text-[10px] text-slate-500">FINISH BY: {wp.finish}</span></div>
              </button>
              {open === index ? <div className="space-y-2 border-t border-slate-200 p-3">
                <div className={"rounded-[2px] border p-2 font-mono text-[11px] " + (wp.tone === "rejected" ? "border-red-200 bg-red-50 text-red-900" : wp.tone === "pending" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-emerald-200 bg-emerald-50 text-emerald-900")}>{wp.tone === "rejected" ? "Next step is paused pending quality evidence." : wp.tone === "pending" ? "Downstream handover is waiting on an upstream check." : "Safety and predecessor checks clear the next team to proceed."}</div>
                <div><div className="mb-1 flex justify-between text-xs"><span className="font-semibold text-slate-700">Work completed</span><span className="font-mono font-bold">{wp.progress}%</span></div><ProgressBar value={wp.progress} tone={wp.progress >= 80 ? "green" : wp.progress < 50 ? "amber" : "blue"} /></div>
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-[2px] border border-slate-200 bg-slate-50 p-2.5 text-xs"><div><div className="font-bold text-slate-900">{wp.engineer}</div><div className="font-mono text-[10px] text-slate-500">{wp.details}</div></div><div className="font-mono text-[10px] text-slate-600">WALKIE-TALKIE: <strong>CHANNEL {wp.channel}</strong></div></div>
              </div> : null}
            </div>
          ))}
        </div>
      </Panel>
      <div className="flex justify-end"><Link href="/dashboard" className="rounded-[2px] bg-[#0d6efd] px-3 py-2 text-[11px] font-bold uppercase tracking-wide text-white">Open live PM roll-up</Link></div>
    </div>
  );
}

function ContractorWorkspace() {
  const [inds, setInds] = useState(["Electric Pipe Bending Machine (1 Machine)", "Heavy Strength Base Grout Cement (120 Bags)"]);
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3"><Kpi title={'24" Process Pipes Investment'} value="₹1.80 Cr" hint="78% fitted & can be billed" /><Kpi title="This Month's Bill" value="₹42.50 Lakh" hint="Engineer checked and approved" /><Kpi title="Unused Pipes Stored in Yard" value="₹39.60 Lakh" hint="Medium sitting-unused risk" /></div>
      <Panel title="Machine Usage & Idle Time Watch" subtitle="Working machines and machines waiting on other teams" action={<button onClick={() => window.alert("Idle machine notice prepared.")} className="rounded-[2px] bg-amber-800 px-2.5 py-1 text-[11px] font-mono text-white">Send Idle Machine Report</button>}>
        <div className="grid gap-3 md:grid-cols-2 text-xs"><Machine name="Heavy Crane SANY-80T" note="Lifting big pipes in Bay B" status="WORKED 4.2 HOURS" cost="Rent: ₹18,900" /><Machine name="Excavator EX-04" note="Idle · waiting for ground survey team" status="IDLE FOR 1.8 HOURS" cost="Wasted Cost: ₹6,300" danger /></div>
      </Panel>
      <Panel title="Monthly Bill Calculation & Final In-Hand Payment">
        <div className="grid gap-2 sm:grid-cols-2 md:grid-cols-4 text-xs font-mono">{[["TOTAL WORK SUBMITTED","₹42,50,000"],["SAFETY DEPOSIT HELD (5%)","-₹2,12,500"],["TAX / OTHER DEDUCTIONS","-₹85,000"],["FINAL PAYABLE","₹39,52,500"]].map(([l,v]) => <div key={l} className="rounded-[2px] border border-slate-200 bg-slate-50 p-2"><span className="block text-[10px] text-slate-500">{l}</span><strong className="text-sm">{v}</strong></div>)}</div>
      </Panel>
      <Panel title="Requests for New Tools & Materials from Engineers" action={<Badge tone="pending">{inds.length} requests pending</Badge>}>
        <div className="space-y-2">{inds.map((item) => <div key={item} className="flex flex-wrap items-center justify-between gap-3 rounded-[2px] border border-slate-200 bg-slate-50 p-3"><div><div className="font-bold text-xs text-slate-900">{item}</div><div className="mt-0.5 text-[10px] text-slate-500">Requested by the site engineering team · delivery required at Bay B</div></div><button onClick={() => setInds((current) => current.filter((x) => x !== item))} className="rounded-[2px] bg-[#198754] px-3.5 py-1.5 text-xs font-bold uppercase tracking-wider text-white">Approve</button></div>)}{inds.length === 0 ? <div className="rounded-[2px] border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900">All prototype requests approved.</div> : null}</div>
      </Panel>
    </div>
  );
}

function SiteEngineerWorkspace() {
  const [selected, setSelected] = useState([1, 2]);
  const [approved, setApproved] = useState<number[]>([]);
  const reports = [
    { id: 1, worker: "M. Hazarika (Welder #22)", trade: "Welding", text: "Completed joint J-103 welding and root pass at Bay B", time: "10:45 AM" },
    { id: 2, worker: "D. Phukan (Rigger #07)", trade: "Pipe Lifting", text: "Spool 05 hoisted onto trestle support using Crane CR-17", time: "11:20 AM" },
  ];
  const approve = (id: number) => { setApproved((a) => a.includes(id) ? a : [...a, id]); setSelected((s) => s.filter((x) => x !== id)); };
  return (
    <div className="space-y-4">
      <Panel title="Area B Piping & Pipe Fitting Progress">
        <div className="space-y-3.5"><div><div className="mb-1 flex justify-between text-xs"><span className="font-semibold text-slate-700">Today's Shift Target: Worker Reports Checked</span><span className="font-mono font-bold text-[#086e24]">{Math.min(10, 6 + approved.length)} / 10 Approved</span></div><ProgressBar value={Math.min(100, 60 + approved.length * 10)} tone="green" /></div><div><div className="mb-1 flex justify-between text-xs"><span className="font-semibold text-slate-700">Total Work Completed in Area B</span><span className="font-mono font-bold text-[#0d6efd]">72%</span></div><ProgressBar value={72 + approved.length} tone="blue" /></div></div>
      </Panel>
      <Panel title="Worker Daily Work Reports" subtitle="Check work reported by site workers before adding it to overall progress" action={<button disabled={!selected.length} onClick={() => selected.forEach(approve)} className="rounded-[2px] bg-[#198754] px-3 py-1 text-[11px] font-mono font-bold text-white disabled:opacity-40">APPROVE SELECTED ({selected.length})</button>}>
        <div className="space-y-2.5">{reports.map((r) => approved.includes(r.id) ? null : <div key={r.id} className="flex flex-wrap items-start justify-between gap-3 rounded-[2px] border border-slate-200 bg-slate-50 p-2.5"><div className="flex items-start gap-2.5"><input type="checkbox" checked={selected.includes(r.id)} onChange={() => setSelected((s) => s.includes(r.id) ? s.filter((x) => x !== r.id) : [...s, r.id])} className="mt-1" /><div><div className="flex flex-wrap items-center gap-2"><span className="text-xs font-bold text-slate-900">{r.worker}</span><Badge tone="blue">{r.trade}</Badge></div><div className="mt-0.5 text-xs text-slate-600">"{r.text}"</div><div className="mt-0.5 font-mono text-[10px] text-slate-400">{r.time} · quality token tagged</div></div></div><div className="flex gap-2"><button onClick={() => window.alert("Drawing verification opened for this report.")} className="rounded-[2px] border border-slate-300 px-2.5 py-1 text-[11px] font-mono text-slate-700">Check Drawing</button><button onClick={() => approve(r.id)} className="rounded-[2px] bg-[#198754] px-3.5 py-1 text-xs font-bold uppercase text-white">Approve</button></div></div>)}</div>
      </Panel>
    </div>
  );
}

function SiteOperativeWorkspace() {
  const [text, setText] = useState("");
  const [photo, setPhoto] = useState<string | null>(null);
  const [voice, setVoice] = useState(false);
  const [done, setDone] = useState(false);
  if (done) return <div className="mx-auto max-w-lg rounded-[2px] border border-[#b6ebc4] bg-[#ebfaef] p-8 text-center"><div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-[#198754] text-2xl font-bold text-white">✓</div><h2 className="font-mono text-3xl font-black tracking-wider text-[#086e24]">DONE</h2><p className="mt-2 text-xs font-semibold text-slate-700">Your work report has been sent to the Site Engineer for check.</p><button onClick={() => { setDone(false); setText(""); setPhoto(null); setVoice(false); }} className="mt-5 rounded-[2px] bg-[#198754] px-4 py-2 text-xs font-bold uppercase tracking-wider text-white">Send Another Work Report</button></div>;
  return <div className="mx-auto max-w-lg"><Panel title="Worker Daily Report Entry" subtitle="Record the work you finished today directly from site" action={<Badge tone="approved">Works offline · saves locally</Badge>}><textarea value={text} onChange={(e) => setText(e.target.value)} rows={4} placeholder="Type your work here (e.g. welded 2 joints, placed 1 pipe on stand)..." className="w-full resize-y rounded-[2px] border border-slate-300 p-2.5 text-xs outline-none focus:border-[#0d6efd]" />{voice ? <div className="mt-2 flex items-center justify-between rounded-[2px] border border-slate-300 bg-slate-100 p-2 text-xs font-mono"><span>▶ Voice message recorded · 8 seconds</span><button onClick={() => setVoice(false)} className="font-bold text-amber-800 hover:underline">↺ Record Again</button></div> : null}<div className="mt-3 grid grid-cols-2 gap-2 border-t border-slate-100 pt-2.5"><button onClick={() => { setVoice(true); setText((v) => v || "Bay B line 24 joint J-103 fitup completed, pre-heat treatment checked."); }} className="flex h-12 items-center justify-center gap-2 rounded-[2px] border border-slate-300 bg-slate-50 text-xs font-bold text-slate-800"><span className="h-2.5 w-2.5 rounded-full bg-red-600" /> Speak by Voice</button><label className="flex h-12 cursor-pointer items-center justify-center gap-2 rounded-[2px] border border-slate-300 bg-slate-50 text-xs font-bold text-slate-800"><span>📷 Attach Work Photo</span><input type="file" accept="image/*" className="hidden" onChange={(e) => setPhoto(e.target.files?.[0]?.name ?? null)} /></label></div>{photo ? <div className="mt-2 font-mono text-[10px] text-slate-500">PHOTO SELECTED: {photo.toUpperCase()}</div> : null}<button onClick={() => setDone(true)} disabled={!text.trim() && !photo && !voice} className="mt-4 flex h-12 w-full items-center justify-center rounded-[2px] bg-[#181b22] text-xs font-bold uppercase tracking-wider text-white disabled:opacity-40">Send Work Report</button></Panel></div>;
}

function PlannerWorkspace() {
  return <div className="space-y-4"><Panel title="Schedule Review & Linking Desk" subtitle="Incoming site reports linked directly to the master schedule"><div className="grid gap-3 md:grid-cols-3"><Kpi title="Incoming reports" value="12" hint="Awaiting planner review" /><Kpi title="Needs mapping" value="3" hint="Human attention required" /><Kpi title="Linked today" value="9" hint="Schedule-linked reports" /></div><div className="mt-4 rounded-[2px] border border-blue-200 bg-blue-50 p-3 text-xs text-blue-900">Use the live review queue to compare candidates and approve a schedule-linked activity.</div><Link href="/queue" className="mt-3 inline-flex rounded-[2px] bg-[#0d6efd] px-3 py-2 text-xs font-bold uppercase tracking-wide text-white">Open Live Schedule Desk</Link></Panel></div>;
}

function DisciplineEngineerWorkspace() {
  const [raw, setRaw] = useState("");
  const [standard, setStandard] = useState("");
  const translate = () => {
    const cleaned = raw.trim().replace(/\bfitup\b/gi, "fit-up").replace(/\bwelded\b/gi, "welded");
    setStandard(cleaned ? "Standard engineering wording: " + cleaned + ". Required evidence and quality checks should be attached before approval." : "");
  };
  return <div className="space-y-4"><Panel title="Field Word Translator & Quality Log" subtitle="Convert site-worker shorthand into standard engineering records"><div className="grid gap-4 lg:grid-cols-2"><div><label className="mb-1 block text-[11px] font-bold uppercase text-slate-600">Worker wording</label><textarea value={raw} onChange={(e) => setRaw(e.target.value)} rows={7} placeholder="e.g. spool fitup done, root pass checked..." className="w-full rounded-[2px] border border-slate-300 p-2.5 text-xs outline-none focus:border-[#0d6efd]" /><button onClick={translate} className="mt-2 rounded-[2px] bg-[#0d6efd] px-3 py-2 text-[11px] font-bold uppercase text-white">Translate to Engineering Record</button></div><div className="rounded-[2px] border border-slate-200 bg-slate-50 p-3"><div className="text-[11px] font-bold uppercase text-slate-600">Standard record</div>{standard ? <p className="mt-2 text-xs leading-5 text-slate-800">{standard}</p> : <p className="mt-2 text-xs text-slate-400">Translated wording appears here.</p>}<div className="mt-4 border-t border-slate-200 pt-3 text-[11px] text-slate-500">Quality log: source wording retained, translation shown separately for auditability.</div></div></div></Panel></div>;
}

function Kpi({ title, value, hint }: { title: string; value: string; hint: string }) {
  return <div className="rounded-[2px] border border-slate-300 bg-white p-3.5"><div className="text-[10px] font-bold uppercase text-slate-500">{title}</div><div className="mt-1 font-mono text-xl font-bold text-slate-900">{value}</div><div className="mt-1 text-[11px] text-slate-500">{hint}</div></div>;
}

function Machine({ name, note, status, cost, danger = false }: { name: string; note: string; status: string; cost: string; danger?: boolean }) {
  return <div className={"flex items-center justify-between gap-3 rounded-[2px] border p-2.5 " + (danger ? "border-red-200 bg-red-50" : "border-slate-200 bg-slate-50")}><div><div className={"text-xs font-bold " + (danger ? "text-red-900" : "text-slate-900")}>{name}</div><div className={"text-[11px] " + (danger ? "text-red-700" : "text-slate-500")}>{note}</div></div><div className="text-right"><Badge tone={danger ? "rejected" : "approved"}>{status}</Badge><div className="mt-0.5 text-[11px] font-bold text-slate-700">{cost}</div></div></div>;
}

export function WorkstationShowcase() {
  const [role, setRole] = useState<WorkstationRole>("SITE OPERATIVES");
  const view = useMemo(() => {
    switch (role) {
      case "CLIENT": return <ClientWorkspace />;
      case "PROJECT MANAGER": return <ProjectManagerWorkspace />;
      case "CONTRACTOR": return <ContractorWorkspace />;
      case "SITE ENGINEER": return <SiteEngineerWorkspace />;
      case "PLANNER / PROJECT CONTROLS": return <PlannerWorkspace />;
      case "DISCIPLINE ENGINEER": return <DisciplineEngineerWorkspace />;
      default: return <SiteOperativeWorkspace />;
    }
  }, [role]);
  return <div className="min-h-[calc(100vh-7rem)]"><div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-slate-300 pb-3"><div><div className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">Integrated workstation</div><h1 className="mt-1 text-base font-bold uppercase tracking-wide text-slate-900">{role}</h1></div><label className="flex items-center gap-2 text-[11px] text-slate-600">View role<select value={role} onChange={(e) => setRole(e.target.value as WorkstationRole)} className="rounded-[2px] border border-slate-300 bg-white px-2 py-1.5 font-mono text-[11px] text-slate-800">{ROLES.map((item) => <option key={item}>{item}</option>)}</select></label></div>{view}</div>;
}

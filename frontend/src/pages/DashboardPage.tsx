import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { apiClient } from "@/services/api";

interface Contract { id:string; title:string; status:string; risk_score:number|null; overall_risk:string|null; created_at:string; }
const RISK_COLOR: Record<string,string> = { critical:"#dc2626", high:"#ea580c", medium:"#d97706", low:"#16a34a" };
const STATUS_COLOR: Record<string,string> = { analyzed:"#16a34a", processing:"#d97706", uploaded:"#6366f1", failed:"#dc2626" };

function Nav() {
  const { role, logout } = useAuthStore(); const navigate = useNavigate();
  return (
    <nav style={{ background:"#fff", borderBottom:"1px solid #e2e8f0", padding:"0 2rem", display:"flex", alignItems:"center", justifyContent:"space-between", height:56 }}>
      <div style={{ display:"flex", alignItems:"center", gap:12 }}><span style={{ fontSize:20 }}>⚖</span><span style={{ fontWeight:700, color:"#0f172a" }}>Contract Intelligence</span></div>
      <div style={{ display:"flex", gap:"1.5rem", alignItems:"center" }}>
        {["Dashboard","Contracts","Chat",...(role==="admin"?["Users"]:[""])].filter(Boolean).map(l=>(
          <button key={l} onClick={()=>navigate("/"+( l==="Dashboard"?"":l.toLowerCase()))} style={{ background:"none", border:"none", color:l==="Dashboard"?"#4f46e5":"#475569", fontSize:"0.875rem", cursor:"pointer", fontWeight:l==="Dashboard"?700:500 }}>{l}</button>
        ))}
        <span style={{ background:"#ede9fe", color:"#7c3aed", padding:"2px 10px", borderRadius:20, fontSize:"0.75rem", fontWeight:600 }}>{role}</span>
        <button onClick={async()=>{await logout();navigate("/login");}} style={{ background:"none", border:"1px solid #e2e8f0", borderRadius:8, padding:"4px 12px", fontSize:"0.75rem", color:"#64748b", cursor:"pointer" }}>Sign out</button>
      </div>
    </nav>
  );
}

export default function DashboardPage() {
  const { role } = useAuthStore(); const navigate = useNavigate();
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(()=>{ apiClient.get("/api/v1/contracts").then(r=>setContracts(r.data)).catch(()=>{}).finally(()=>setLoading(false)); },[]);
  const analyzed = contracts.filter(c=>c.status==="analyzed");
  const critical = analyzed.filter(c=>c.overall_risk==="critical").length;
  const high = analyzed.filter(c=>c.overall_risk==="high").length;
  const avgRisk = analyzed.length ? Math.round(analyzed.reduce((s,c)=>s+(c.risk_score||0),0)/analyzed.length) : 0;
  return (
    <div style={{ minHeight:"100vh", background:"#f1f5f9" }}>
      <Nav/>
      <div style={{ maxWidth:1200, margin:"0 auto", padding:"2rem" }}>
        <h1 style={{ fontSize:"1.5rem", fontWeight:700, color:"#0f172a", marginBottom:"1.5rem" }}>Dashboard</h1>
        <div style={{ display:"flex", gap:"1rem", marginBottom:"2rem", flexWrap:"wrap" }}>
          {[
            { label:"Total Contracts", value:contracts.length, color:"#0f172a" },
            { label:"Analyzed", value:analyzed.length, color:"#16a34a" },
            { label:"Avg Risk Score", value:avgRisk||"—", color:avgRisk>70?"#dc2626":avgRisk>40?"#d97706":"#16a34a" },
            { label:"Critical / High", value:critical+" / "+high, color:"#dc2626" },
          ].map(s=>(
            <div key={s.label} style={{ background:"#fff", borderRadius:12, padding:"1.5rem", boxShadow:"0 1px 4px rgba(0,0,0,0.06)", flex:1, minWidth:160 }}>
              <p style={{ color:"#64748b", fontSize:"0.75rem", fontWeight:600, textTransform:"uppercase", letterSpacing:"0.05em", margin:0 }}>{s.label}</p>
              <p style={{ fontSize:"2rem", fontWeight:700, color:s.color, margin:"0.25rem 0 0" }}>{s.value}</p>
            </div>
          ))}
        </div>
        <div style={{ background:"#fff", borderRadius:12, boxShadow:"0 1px 4px rgba(0,0,0,0.06)", overflow:"hidden" }}>
          <div style={{ padding:"1rem 1.5rem", borderBottom:"1px solid #f1f5f9", display:"flex", justifyContent:"space-between", alignItems:"center" }}>
            <h2 style={{ fontSize:"1rem", fontWeight:600, color:"#0f172a", margin:0 }}>Contracts</h2>
            {(role==="admin"||role==="reviewer")&&<button onClick={()=>navigate("/contracts")} style={{ background:"#4f46e5", color:"#fff", border:"none", borderRadius:8, padding:"6px 16px", fontSize:"0.875rem", fontWeight:600, cursor:"pointer" }}>+ Upload</button>}
          </div>
          {loading ? <div style={{ padding:"3rem", textAlign:"center", color:"#94a3b8" }}>Loading…</div>
          : contracts.length===0 ? <div style={{ padding:"3rem", textAlign:"center", color:"#94a3b8" }}>No contracts yet.</div>
          : <table style={{ width:"100%", borderCollapse:"collapse" }}>
              <thead><tr style={{ background:"#f8fafc" }}>
                {["Title","Status","Risk Score","Risk Level","Uploaded"].map(h=>(
                  <th key={h} style={{ padding:"0.75rem 1.5rem", textAlign:"left", fontSize:"0.75rem", fontWeight:600, color:"#64748b", textTransform:"uppercase" }}>{h}</th>
                ))}
              </tr></thead>
              <tbody>{contracts.slice(0,10).map(c=>(
                <tr key={c.id} style={{ borderTop:"1px solid #f1f5f9", cursor:"pointer" }} onClick={()=>navigate("/contracts/"+c.id)}
                  onMouseOver={e=>(e.currentTarget.style.background="#f8fafc")} onMouseOut={e=>(e.currentTarget.style.background="")}>
                  <td style={{ padding:"1rem 1.5rem", fontSize:"0.875rem", fontWeight:500, color:"#0f172a" }}>{c.title}</td>
                  <td style={{ padding:"1rem 1.5rem" }}><span style={{ background:(STATUS_COLOR[c.status]||"#64748b")+"20", color:STATUS_COLOR[c.status]||"#64748b", padding:"2px 10px", borderRadius:20, fontSize:"0.75rem", fontWeight:600 }}>{c.status}</span></td>
                  <td style={{ padding:"1rem 1.5rem", fontSize:"0.875rem", color:"#374151" }}>{c.risk_score??""}</td>
                  <td style={{ padding:"1rem 1.5rem" }}>{c.overall_risk?<span style={{ background:(RISK_COLOR[c.overall_risk]||"#94a3b8")+"20", color:RISK_COLOR[c.overall_risk]||"#94a3b8", padding:"2px 10px", borderRadius:20, fontSize:"0.75rem", fontWeight:600 }}>{c.overall_risk}</span>:<span style={{ color:"#94a3b8" }}>—</span>}</td>
                  <td style={{ padding:"1rem 1.5rem", fontSize:"0.875rem", color:"#64748b" }}>{new Date(c.created_at).toLocaleDateString()}</td>
                </tr>
              ))}</tbody>
            </table>}
        </div>
      </div>
    </div>
  );
}

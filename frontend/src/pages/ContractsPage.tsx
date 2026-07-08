import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { apiClient, getErrorMessage } from "@/services/api";

interface UploadResult { contract_id:string; status:string; message:string; }
interface Clause { id:string; clause_type:string; title:string; summary:string; raw_text:string|null; risk_score:number|null; risk_level:string|null; risk_reason:string|null; flagged:boolean; }
const RISK_COLOR: Record<string,string> = { critical:"#dc2626", high:"#ea580c", medium:"#d97706", low:"#16a34a" };

function Nav() {
  const { logout } = useAuthStore(); const navigate = useNavigate();
  return (
    <nav style={{ background:"#fff", borderBottom:"1px solid #e2e8f0", padding:"0 2rem", display:"flex", alignItems:"center", justifyContent:"space-between", height:56 }}>
      <div style={{ display:"flex", alignItems:"center", gap:12 }}><span style={{ fontSize:20 }}>⚖</span><span style={{ fontWeight:700, color:"#0f172a" }}>Contract Intelligence</span></div>
      <div style={{ display:"flex", gap:"1.5rem", alignItems:"center" }}>
        {["Dashboard","Contracts","Chat"].map(l=>(
          <button key={l} onClick={()=>navigate("/"+( l==="Dashboard"?"":l.toLowerCase()))} style={{ background:"none", border:"none", color:l==="Contracts"?"#4f46e5":"#475569", fontSize:"0.875rem", cursor:"pointer", fontWeight:l==="Contracts"?700:500 }}>{l}</button>
        ))}
        <button onClick={async()=>{await logout();navigate("/login");}} style={{ background:"none", border:"1px solid #e2e8f0", borderRadius:8, padding:"4px 12px", fontSize:"0.75rem", color:"#64748b", cursor:"pointer" }}>Sign out</button>
      </div>
    </nav>
  );
}

export default function ContractsPage() {
  const { role } = useAuthStore();
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<UploadResult|null>(null);
  const [error, setError] = useState("");
  const [clauses, setClauses] = useState<Clause[]>([]);
  const [polling, setPolling] = useState(false);
  const [expanded, setExpanded] = useState<string|null>(null);

  const upload = async (file: File) => {
    setUploading(true); setError(""); setResult(null); setClauses([]);
    const form = new FormData(); form.append("file", file);
    try {
      const res = await apiClient.post<UploadResult>("/api/v1/contracts/upload", form, { headers:{"Content-Type":"multipart/form-data"} });
      setResult(res.data);
      poll(res.data.contract_id);
    } catch(err) { setError(getErrorMessage(err)); }
    finally { setUploading(false); }
  };

  const poll = async (id: string) => {
    setPolling(true);
    for(let i=0;i<20;i++) {
      await new Promise(r=>setTimeout(r,3000));
      try {
        const s = await apiClient.get("/api/v1/contracts/"+id);
        if(s.data.status==="analyzed") {
          const cr = await apiClient.get("/api/v1/clauses/"+id);
          setClauses(cr.data); setPolling(false); return;
        }
        if(s.data.status==="failed") break;
      } catch { break; }
    }
    setPolling(false);
  };

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragging(false);
    const f = e.dataTransfer.files[0]; if(f) upload(f);
  }, []);

  return (
    <div style={{ minHeight:"100vh", background:"#f1f5f9" }}>
      <Nav/>
      <div style={{ maxWidth:1100, margin:"0 auto", padding:"2rem" }}>
        <h1 style={{ fontSize:"1.5rem", fontWeight:700, color:"#0f172a", marginBottom:"1.5rem" }}>Contracts</h1>
        {(role==="admin"||role==="reviewer") && (
          <div onDragOver={e=>{e.preventDefault();setDragging(true);}} onDragLeave={()=>setDragging(false)} onDrop={onDrop}
            onClick={()=>document.getElementById("fi")?.click()}
            style={{ border:"2px dashed "+(dragging?"#4f46e5":"#cbd5e1"), borderRadius:12, padding:"3rem", textAlign:"center", background:dragging?"#ede9fe":"#fff", marginBottom:"2rem", cursor:"pointer", transition:"all 0.2s" }}>
            <div style={{ fontSize:40, marginBottom:"1rem" }}>📄</div>
            <p style={{ fontSize:"1rem", fontWeight:600, color:"#374151", margin:0 }}>{uploading?"Uploading…":"Drop a contract here or click to browse"}</p>
            <p style={{ color:"#94a3b8", fontSize:"0.875rem", marginTop:4 }}>PDF or DOCX — max 50 MB</p>
            <input id="fi" type="file" accept=".pdf,.docx,.doc" style={{ display:"none" }} onChange={e=>{const f=e.target.files?.[0];if(f)upload(f);}} />
          </div>
        )}
        {error && <div style={{ background:"#fef2f2", border:"1px solid #fecaca", borderRadius:8, padding:"0.75rem 1rem", color:"#dc2626", marginBottom:"1rem" }}>{error}</div>}
        {result && <div style={{ background:"#f0fdf4", border:"1px solid #bbf7d0", borderRadius:8, padding:"0.75rem 1rem", color:"#16a34a", marginBottom:"1rem" }}>✓ {result.message}</div>}
        {polling && (
          <div style={{ background:"#fff", borderRadius:12, padding:"3rem", textAlign:"center", color:"#64748b", boxShadow:"0 1px 4px rgba(0,0,0,0.06)" }}>
            <div style={{ fontSize:32, marginBottom:"1rem" }}>⚙️</div>
            <p style={{ fontWeight:600 }}>Analysing contract…</p>
            <p style={{ color:"#94a3b8", fontSize:"0.875rem" }}>Safety → Extraction → Risk scoring → Validation</p>
          </div>
        )}
        {clauses.length>0 && (
          <div>
            <h2 style={{ fontSize:"1.1rem", fontWeight:700, color:"#0f172a", marginBottom:"1rem" }}>{clauses.length} Clauses Extracted</h2>
            {clauses.map(c=>(
              <div key={c.id} style={{ background:"#fff", borderRadius:10, marginBottom:"0.75rem", boxShadow:"0 1px 4px rgba(0,0,0,0.05)", border:c.flagged?"1px solid #fecaca":"1px solid #f1f5f9", overflow:"hidden" }}>
                <div onClick={()=>setExpanded(expanded===c.id?null:c.id)} style={{ padding:"1rem 1.25rem", cursor:"pointer", display:"flex", justifyContent:"space-between", alignItems:"center" }}>
                  <div>
                    <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:4 }}>
                      {c.flagged&&<span style={{ color:"#dc2626", fontSize:"0.75rem" }}>⚠ Flagged</span>}
                      <span style={{ fontSize:"0.75rem", color:"#6366f1", fontWeight:600, background:"#ede9fe", padding:"1px 8px", borderRadius:10 }}>{c.clause_type}</span>
                    </div>
                    <p style={{ fontSize:"0.9rem", fontWeight:600, color:"#0f172a", margin:0 }}>{c.title||"Untitled"}</p>
                    <p style={{ fontSize:"0.8rem", color:"#64748b", margin:"2px 0 0" }}>{(c.summary||"").slice(0,120)}…</p>
                  </div>
                  {c.risk_score!==null&&(
                    <div style={{ textAlign:"right", flexShrink:0, marginLeft:"1rem" }}>
                      <div style={{ fontSize:"1.5rem", fontWeight:700, color:RISK_COLOR[c.risk_level||"low"]||"#64748b" }}>{c.risk_score}</div>
                      <div style={{ fontSize:"0.7rem", color:"#94a3b8" }}>risk</div>
                    </div>
                  )}
                </div>
                {expanded===c.id&&(
                  <div style={{ padding:"1rem 1.25rem", borderTop:"1px solid #f1f5f9", background:"#f8fafc" }}>
                    {c.risk_reason&&<p style={{ fontSize:"0.875rem", color:"#475569", margin:"0 0 0.5rem" }}><strong>Risk: </strong>{c.risk_reason}</p>}
                    {c.raw_text&&<p style={{ fontSize:"0.8rem", color:"#64748b", background:"#fff", padding:"0.75rem", borderRadius:6, fontFamily:"monospace", lineHeight:1.6, margin:0 }}>{c.raw_text.slice(0,500)}…</p>}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

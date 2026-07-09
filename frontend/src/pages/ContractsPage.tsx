import { useState, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { apiClient, getErrorMessage } from "@/services/api";

interface UploadResult { contract_id:string; status:string; message:string; }
interface Contract { id:string; title:string; status:string; overall_risk:string|null; risk_score:number|null; created_at:string; }
interface Clause { id:string; clause_type:string; title:string; summary:string; raw_text:string|null; risk_score:number|null; risk_level:string|null; risk_reason:string|null; flagged:boolean; }
const RISK_COLOR: Record<string,string> = { critical:"#dc2626", high:"#ea580c", medium:"#d97706", low:"#16a34a" };
const STATUS_COLOR: Record<string,string> = { analyzed:"#16a34a", processing:"#d97706", uploaded:"#6366f1", failed:"#dc2626" };

function Nav() {
  const { logout } = useAuthStore(); const navigate = useNavigate();
  return (
    <nav style={{ background:"#fff", borderBottom:"1px solid #e2e8f0", padding:"0 2rem", display:"flex", alignItems:"center", justifyContent:"space-between", height:56 }}>
      <div style={{ display:"flex", alignItems:"center", gap:12 }}><span style={{ fontSize:20 }}>⚖</span><span style={{ fontWeight:700, color:"#0f172a" }}>Contract Intelligence</span></div>
      <div style={{ display:"flex", gap:"1.5rem", alignItems:"center" }}>
        {["Dashboard","Contracts","Chat"].map(l=>(
          <button key={l} onClick={()=>navigate("/"+( l==="Dashboard"?"":l.toLowerCase()))}
            style={{ background:"none", border:"none", color:l==="Contracts"?"#4f46e5":"#475569", fontSize:"0.875rem", cursor:"pointer", fontWeight:l==="Contracts"?700:500 }}>{l}</button>
        ))}
        <button onClick={async()=>{await logout();navigate("/login");}} style={{ background:"none", border:"1px solid #e2e8f0", borderRadius:8, padding:"4px 12px", fontSize:"0.75rem", color:"#64748b", cursor:"pointer" }}>Sign out</button>
      </div>
    </nav>
  );
}

export default function ContractsPage() {
  const { role } = useAuthStore();
  // List view state
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  // Selected contract clause view
  const [selectedContract, setSelectedContract] = useState<Contract|null>(null);
  const [clauses, setClauses] = useState<Clause[]>([]);
  const [loadingClauses, setLoadingClauses] = useState(false);
  const [expanded, setExpanded] = useState<string|null>(null);
  const [feedback, setFeedback] = useState<Record<string,"up"|"down"|null>>({});
  const [feedbackLoading, setFeedbackLoading] = useState<string|null>(null);
  // Upload state
  const [showUpload, setShowUpload] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<UploadResult|null>(null);
  const [polling, setPolling] = useState(false);
  const [error, setError] = useState("");

  // Load contract list on mount
  useEffect(() => {
    apiClient.get("/api/v1/contracts")
      .then(r => setContracts(r.data))
      .catch(() => {})
      .finally(() => setLoadingList(false));
  }, []);

  // Open a contract and load its clauses
  const openContract = async (c: Contract) => {
    setSelectedContract(c); setClauses([]); setFeedback({}); setExpanded(null);
    if (c.status !== "analyzed") return;
    setLoadingClauses(true);
    try {
      const r = await apiClient.get("/api/v1/clauses/" + c.id);
      setClauses(r.data);
    } catch { /* no clauses yet */ }
    finally { setLoadingClauses(false); }
  };

  const submitFeedback = async (clauseId: string, isPositive: boolean) => {
    if (!selectedContract) return;
    setFeedbackLoading(clauseId);
    try {
      await apiClient.post("/api/v1/feedback", {
        clause_id: clauseId, contract_id: selectedContract.id,
        is_positive: isPositive, feedback_target: "risk_score",
        notes: isPositive ? "Risk score accurate" : "Risk score needs adjustment",
      });
      setFeedback(prev => ({ ...prev, [clauseId]: isPositive ? "up" : "down" }));
    } catch { /* silent */ }
    finally { setFeedbackLoading(null); }
  };

  const upload = async (file: File) => {
    setUploading(true); setError(""); setUploadResult(null);
    const form = new FormData(); form.append("file", file);
    try {
      const res = await apiClient.post<UploadResult>("/api/v1/contracts/upload", form,
        { headers:{"Content-Type":"multipart/form-data"} });
      setUploadResult(res.data);
      pollUntilDone(res.data.contract_id);
    } catch(err) { setError(getErrorMessage(err)); }
    finally { setUploading(false); }
  };

  const pollUntilDone = async (id: string) => {
    setPolling(true);
    for(let i=0;i<20;i++) {
      await new Promise(r=>setTimeout(r,3000));
      try {
        const s = await apiClient.get("/api/v1/contracts/"+id);
        if(s.data.status==="analyzed") {
          // Refresh list and open the new contract
          const listRes = await apiClient.get("/api/v1/contracts");
          setContracts(listRes.data);
          const newContract = listRes.data.find((c: Contract) => c.id === id);
          if (newContract) openContract(newContract);
          setShowUpload(false); setPolling(false); return;
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

  // ── Clause detail view ─────────────────────────────────────────────────────
  if (selectedContract) {
    return (
      <div style={{ minHeight:"100vh", background:"#f1f5f9" }}>
        <Nav/>
        <div style={{ maxWidth:1100, margin:"0 auto", padding:"2rem" }}>
          {/* Back button */}
          <div style={{ display:"flex", alignItems:"center", gap:"1rem", marginBottom:"1.5rem" }}>
            <button onClick={()=>setSelectedContract(null)}
              style={{ background:"#fff", border:"1px solid #e2e8f0", borderRadius:8, padding:"6px 14px", fontSize:"0.875rem", cursor:"pointer", color:"#374151" }}>
              ← Back to Contracts
            </button>
            <div>
              <h1 style={{ fontSize:"1.25rem", fontWeight:700, color:"#0f172a", margin:0 }}>{selectedContract.title}</h1>
              <div style={{ display:"flex", gap:8, marginTop:4 }}>
                <span style={{ fontSize:"0.75rem", background:(STATUS_COLOR[selectedContract.status]||"#94a3b8")+"20", color:STATUS_COLOR[selectedContract.status]||"#94a3b8", padding:"2px 10px", borderRadius:20, fontWeight:600 }}>{selectedContract.status}</span>
                {selectedContract.overall_risk&&<span style={{ fontSize:"0.75rem", background:(RISK_COLOR[selectedContract.overall_risk]||"#94a3b8")+"20", color:RISK_COLOR[selectedContract.overall_risk]||"#94a3b8", padding:"2px 10px", borderRadius:20, fontWeight:600 }}>{selectedContract.overall_risk} risk</span>}
                {selectedContract.risk_score&&<span style={{ fontSize:"0.75rem", color:"#64748b" }}>Avg score: {selectedContract.risk_score}</span>}
              </div>
            </div>
          </div>

          {loadingClauses && <div style={{ background:"#fff", borderRadius:12, padding:"3rem", textAlign:"center", color:"#64748b" }}>Loading clauses…</div>}

          {selectedContract.status!=="analyzed"&&!loadingClauses&&(
            <div style={{ background:"#fff", borderRadius:12, padding:"3rem", textAlign:"center", color:"#64748b", boxShadow:"0 1px 4px rgba(0,0,0,0.06)" }}>
              <div style={{ fontSize:32, marginBottom:"1rem" }}>⚙️</div>
              <p style={{ fontWeight:600 }}>Contract is {selectedContract.status}</p>
              <p style={{ color:"#94a3b8", fontSize:"0.875rem" }}>Refresh the page in a moment to see extracted clauses.</p>
            </div>
          )}

          {clauses.length>0&&(
            <div>
              <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:"1rem" }}>
                <h2 style={{ fontSize:"1rem", fontWeight:700, color:"#0f172a", margin:0 }}>{clauses.length} Clauses Extracted</h2>
                <span style={{ fontSize:"0.8rem", color:"#64748b" }}>Expand a clause · Use 👍👎 to validate risk scores</span>
              </div>
              {clauses.map(c=>(
                <div key={c.id} style={{ background:"#fff", borderRadius:10, marginBottom:"0.75rem", boxShadow:"0 1px 4px rgba(0,0,0,0.05)", border:c.flagged?"1px solid #fecaca":"1px solid #f1f5f9", overflow:"hidden" }}>
                  <div onClick={()=>setExpanded(expanded===c.id?null:c.id)}
                    style={{ padding:"1rem 1.25rem", cursor:"pointer", display:"flex", justifyContent:"space-between", alignItems:"center" }}>
                    <div>
                      <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:4 }}>
                        {c.flagged&&<span style={{ color:"#dc2626", fontSize:"0.75rem", fontWeight:600 }}>⚠ Flagged</span>}
                        <span style={{ fontSize:"0.75rem", color:"#6366f1", fontWeight:600, background:"#ede9fe", padding:"1px 8px", borderRadius:10 }}>{c.clause_type}</span>
                        {feedback[c.id]&&<span style={{ fontSize:"0.7rem", color:feedback[c.id]==="up"?"#16a34a":"#dc2626" }}>{feedback[c.id]==="up"?"✓ Validated":"✗ Flagged as incorrect"}</span>}
                      </div>
                      <p style={{ fontSize:"0.9rem", fontWeight:600, color:"#0f172a", margin:0 }}>{c.title||"Untitled"}</p>
                      <p style={{ fontSize:"0.8rem", color:"#64748b", margin:"2px 0 0" }}>{(c.summary||"").slice(0,120)}{(c.summary||"").length>120?"…":""}</p>
                    </div>
                    {c.risk_score!==null&&(
                      <div style={{ textAlign:"right", flexShrink:0, marginLeft:"1rem" }}>
                        <div style={{ fontSize:"1.5rem", fontWeight:700, color:RISK_COLOR[c.risk_level||"low"]||"#64748b" }}>{c.risk_score}</div>
                        <div style={{ fontSize:"0.7rem", color:"#94a3b8" }}>{c.risk_level||""} risk</div>
                      </div>
                    )}
                  </div>
                  {expanded===c.id&&(
                    <div style={{ padding:"1rem 1.25rem", borderTop:"1px solid #f1f5f9", background:"#f8fafc" }}>
                      {c.risk_reason&&<p style={{ fontSize:"0.875rem", color:"#475569", margin:"0 0 0.75rem" }}><strong>Risk Analysis: </strong>{c.risk_reason}</p>}
                      {c.raw_text&&(
                        <div style={{ marginBottom:"0.75rem" }}>
                          <p style={{ fontSize:"0.75rem", fontWeight:600, color:"#374151", margin:"0 0 4px" }}>Clause Text:</p>
                          <p style={{ fontSize:"0.8rem", color:"#64748b", background:"#fff", padding:"0.75rem", borderRadius:6, fontFamily:"monospace", lineHeight:1.6, margin:0, border:"1px solid #e2e8f0" }}>
                            {c.raw_text.slice(0,600)}{c.raw_text.length>600?"…":""}
                          </p>
                        </div>
                      )}
                      <div style={{ display:"flex", alignItems:"center", gap:"0.5rem", paddingTop:"0.5rem", borderTop:"1px solid #e2e8f0" }}>
                        <span style={{ fontSize:"0.8rem", color:"#64748b", fontWeight:500 }}>Is this risk score accurate?</span>
                        <button onClick={e=>{e.stopPropagation();submitFeedback(c.id,true);}} disabled={feedbackLoading===c.id}
                          style={{ background:feedback[c.id]==="up"?"#16a34a":"#f1f5f9", color:feedback[c.id]==="up"?"#fff":"#374151", border:"none", borderRadius:8, padding:"6px 14px", fontSize:"0.8rem", cursor:"pointer", fontWeight:600 }}>
                          👍 {feedback[c.id]==="up"?"Confirmed":"Accurate"}
                        </button>
                        <button onClick={e=>{e.stopPropagation();submitFeedback(c.id,false);}} disabled={feedbackLoading===c.id}
                          style={{ background:feedback[c.id]==="down"?"#dc2626":"#f1f5f9", color:feedback[c.id]==="down"?"#fff":"#374151", border:"none", borderRadius:8, padding:"6px 14px", fontSize:"0.8rem", cursor:"pointer", fontWeight:600 }}>
                          👎 {feedback[c.id]==="down"?"Flagged":"Needs Review"}
                        </button>
                        {feedback[c.id]&&feedbackLoading!==c.id&&<span style={{ fontSize:"0.75rem", color:"#16a34a" }}>✓ Feedback saved — helps calibrate AI scoring</span>}
                      </div>
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

  // ── Contract list view ─────────────────────────────────────────────────────
  return (
    <div style={{ minHeight:"100vh", background:"#f1f5f9" }}>
      <Nav/>
      <div style={{ maxWidth:1100, margin:"0 auto", padding:"2rem" }}>
        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:"1.5rem" }}>
          <h1 style={{ fontSize:"1.5rem", fontWeight:700, color:"#0f172a", margin:0 }}>Contracts</h1>
          {(role==="admin"||role==="reviewer")&&(
            <button onClick={()=>{setShowUpload(!showUpload);setError("");setUploadResult(null);}}
              style={{ background:"#4f46e5", color:"#fff", border:"none", borderRadius:8, padding:"8px 18px", fontSize:"0.875rem", fontWeight:600, cursor:"pointer" }}>
              {showUpload?"✕ Cancel":"+ Upload Contract"}
            </button>
          )}
        </div>

        {/* Upload panel */}
        {showUpload&&(
          <div style={{ background:"#fff", borderRadius:12, padding:"1.5rem", marginBottom:"1.5rem", boxShadow:"0 1px 4px rgba(0,0,0,0.06)" }}>
            <div onDragOver={e=>{e.preventDefault();setDragging(true);}} onDragLeave={()=>setDragging(false)} onDrop={onDrop}
              onClick={()=>document.getElementById("fi")?.click()}
              style={{ border:"2px dashed "+(dragging?"#4f46e5":"#cbd5e1"), borderRadius:10, padding:"2.5rem", textAlign:"center", background:dragging?"#ede9fe":"#f8fafc", cursor:"pointer" }}>
              <div style={{ fontSize:36, marginBottom:"0.75rem" }}>📄</div>
              <p style={{ fontSize:"1rem", fontWeight:600, color:"#374151", margin:0 }}>{uploading?"Uploading…":"Drop a contract here or click to browse"}</p>
              <p style={{ color:"#94a3b8", fontSize:"0.875rem", marginTop:4 }}>PDF, DOCX, or TXT — max 50 MB</p>
              <input id="fi" type="file" accept=".pdf,.docx,.doc,.txt" style={{ display:"none" }}
                onChange={e=>{const f=e.target.files?.[0];if(f)upload(f);}} />
            </div>
            {error&&<div style={{ background:"#fef2f2", border:"1px solid #fecaca", borderRadius:8, padding:"0.75rem", color:"#dc2626", marginTop:"1rem", fontSize:"0.875rem" }}>{error}</div>}
            {uploadResult&&<div style={{ background:"#f0fdf4", border:"1px solid #bbf7d0", borderRadius:8, padding:"0.75rem", color:"#16a34a", marginTop:"1rem", fontSize:"0.875rem" }}>✓ {uploadResult.message}</div>}
            {polling&&<div style={{ textAlign:"center", padding:"1rem", color:"#64748b", fontSize:"0.875rem" }}>⚙️ Analysing contract — will open automatically when complete…</div>}
          </div>
        )}

        {/* Contract list */}
        <div style={{ background:"#fff", borderRadius:12, boxShadow:"0 1px 4px rgba(0,0,0,0.06)", overflow:"hidden" }}>
          <div style={{ padding:"1rem 1.5rem", borderBottom:"1px solid #f1f5f9" }}>
            <h2 style={{ fontSize:"1rem", fontWeight:600, color:"#0f172a", margin:0 }}>
              {role==="reviewer"?"Your Assigned Contracts":"All Contracts"} ({contracts.length})
            </h2>
          </div>
          {loadingList?<div style={{ padding:"3rem", textAlign:"center", color:"#94a3b8" }}>Loading…</div>
          :contracts.length===0?<div style={{ padding:"3rem", textAlign:"center", color:"#94a3b8" }}>
            {role==="reviewer"?"No contracts assigned to you yet. Contact your admin.":"No contracts yet. Upload your first contract."}
          </div>
          :<table style={{ width:"100%", borderCollapse:"collapse" }}>
            <thead><tr style={{ background:"#f8fafc" }}>
              {["Title","Status","Risk Score","Risk Level","Uploaded","Actions"].map(h=>(
                <th key={h} style={{ padding:"0.75rem 1.25rem", textAlign:"left", fontSize:"0.75rem", fontWeight:600, color:"#64748b", textTransform:"uppercase" }}>{h}</th>
              ))}
            </tr></thead>
            <tbody>{contracts.map(c=>(
              <tr key={c.id} style={{ borderTop:"1px solid #f1f5f9" }}>
                <td style={{ padding:"1rem 1.25rem", fontSize:"0.875rem", fontWeight:500, color:"#0f172a" }}>{c.title}</td>
                <td style={{ padding:"1rem 1.25rem" }}><span style={{ background:(STATUS_COLOR[c.status]||"#94a3b8")+"20", color:STATUS_COLOR[c.status]||"#94a3b8", padding:"2px 10px", borderRadius:20, fontSize:"0.75rem", fontWeight:600 }}>{c.status}</span></td>
                <td style={{ padding:"1rem 1.25rem", fontSize:"0.875rem", color:"#374151" }}>{c.risk_score??""}</td>
                <td style={{ padding:"1rem 1.25rem" }}>{c.overall_risk?<span style={{ background:(RISK_COLOR[c.overall_risk]||"#94a3b8")+"20", color:RISK_COLOR[c.overall_risk]||"#94a3b8", padding:"2px 10px", borderRadius:20, fontSize:"0.75rem", fontWeight:600 }}>{c.overall_risk}</span>:<span style={{ color:"#94a3b8" }}>—</span>}</td>
                <td style={{ padding:"1rem 1.25rem", fontSize:"0.875rem", color:"#64748b" }}>{new Date(c.created_at).toLocaleDateString()}</td>
                <td style={{ padding:"1rem 1.25rem" }}>
                  <button onClick={()=>openContract(c)}
                    style={{ background:"#4f46e5", color:"#fff", border:"none", borderRadius:6, padding:"5px 14px", fontSize:"0.75rem", fontWeight:600, cursor:"pointer" }}>
                    View Clauses
                  </button>
                </td>
              </tr>
            ))}</tbody>
          </table>}
        </div>
      </div>
    </div>
  );
}

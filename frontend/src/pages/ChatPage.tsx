import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { apiClient, getErrorMessage } from "@/services/api";

interface Msg { id:string; role:"user"|"assistant"; content:string; citations?:Array<{index:number;section_path:string;clause_type:string}>; isError?:boolean; }
// Contract selector state
function useContracts() {
  const [contracts, setContracts] = useState<Array<{id:string;title:string}>>([]);
  useEffect(() => {
    apiClient.get("/api/v1/contracts")
      .then(r => setContracts(r.data.filter((c:any) => c.status === "analyzed")))
      .catch(() => {});
  }, []);
  return contracts;
}

const SUGGESTED = ["What is the liability cap?","When does the contract auto-renew?","What are the confidentiality obligations?","What payment amounts are due?","Are there any critical risk clauses?"];

function Nav() {
  const { role, logout } = useAuthStore(); const navigate = useNavigate();
  return (
    <nav style={{ background:"#fff", borderBottom:"1px solid #e2e8f0", padding:"0 2rem", display:"flex", alignItems:"center", justifyContent:"space-between", height:56, flexShrink:0 }}>
      <div style={{ display:"flex", alignItems:"center", gap:12 }}><span style={{ fontSize:20 }}>⚖</span><span style={{ fontWeight:700, color:"#0f172a" }}>Contract Intelligence</span></div>
      <div style={{ display:"flex", gap:"1.5rem", alignItems:"center" }}>
        {["Dashboard","Contracts","Chat"].map(l=>(
          <button key={l} onClick={()=>navigate("/"+( l==="Dashboard"?"":l.toLowerCase()))} style={{ background:"none", border:"none", color:l==="Chat"?"#4f46e5":"#475569", fontSize:"0.875rem", cursor:"pointer", fontWeight:l==="Chat"?700:500 }}>{l}</button>
        ))}
        <span style={{ background:"#ede9fe", color:"#7c3aed", padding:"2px 10px", borderRadius:20, fontSize:"0.75rem", fontWeight:600 }}>{role}</span>
        <button onClick={async()=>{await logout();navigate("/login");}} style={{ background:"none", border:"1px solid #e2e8f0", borderRadius:8, padding:"4px 12px", fontSize:"0.75rem", color:"#64748b", cursor:"pointer" }}>Sign out</button>
      </div>
    </nav>
  );
}

function formatMessage(text: string): React.ReactNode {
  if (!text) return null;
  const lines = text.split("\n");
  return (
    <div>
      {lines.map((line, i) => {
        // Bullet line
        if (line.startsWith("• ") || line.startsWith("* ")) {
          const inner = line.slice(2);
          return (
            <div key={i} style={{ display:"flex", gap:8, margin:"3px 0", alignItems:"flex-start" }}>
              <span style={{ color:"#4f46e5", fontWeight:700, flexShrink:0, marginTop:2 }}>•</span>
              <span style={{ lineHeight:1.6 }}>{renderBold(inner)}</span>
            </div>
          );
        }
        // Summary line
        if (line.startsWith("**Summary:**") || line.startsWith("Summary:")) {
          return <div key={i} style={{ marginTop:8, padding:"6px 10px", background:"#f0fdf4", borderRadius:6, borderLeft:"3px solid #16a34a", fontSize:"0.875rem" }}>{renderBold(line)}</div>;
        }
        // Table row
        if (line.startsWith("|") && line.endsWith("|")) {
          if (line.includes("---")) return null;
          const cells = line.split("|").filter(c => c.trim());
          return (
            <div key={i} style={{ display:"flex", gap:0, borderBottom:"1px solid #f1f5f9" }}>
              {cells.map((c, j) => (
                <div key={j} style={{ flex:1, padding:"4px 8px", fontSize:"0.8rem", fontWeight:j===0?"600":"400", background:j===0?"#f8fafc":"#fff" }}>
                  {renderBold(c.trim())}
                </div>
              ))}
            </div>
          );
        }
        // Empty line
        if (!line.trim()) return <div key={i} style={{ height:8 }} />;
        // Normal line
        return <div key={i} style={{ marginBottom:2, lineHeight:1.6 }}>{renderBold(line)}</div>;
      })}
    </div>
  );
}

function renderBold(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("**") && p.endsWith("**")
          ? <strong key={i} style={{ color:"#0f172a" }}>{p.slice(2,-2)}</strong>
          : <span key={i}>{p}</span>
      )}
    </>
  );
}

export default function ChatPage() {
  const loadHistory = async (cid: string) => {
    try {
      const res = await apiClient.get(`/api/v1/chat/history?contract_id=${cid}&limit=20`);
      if (res.data && res.data.length > 0) {
        const history: Msg[] = res.data.map((m: any, i: number) => ({
          id: `hist-${i}`,
          role: m.role as "user"|"assistant",
          content: m.content,
        }));
        setMsgs([
          { id:"w", role:"assistant", content:"Welcome back! Continuing your previous conversation:" },
          ...history
        ]);
      }
    } catch (e) {
      // No history yet — keep default message
    }
  };

  const [msgs, setMsgs] = useState<Msg[]>([{ id:"w", role:"assistant", content:"Hello! Ask me anything about your contracts — liability caps, renewal dates, payment terms, risks." }]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId] = useState(()=>crypto.randomUUID());
  const [selectedContractId, setSelectedContractId] = useState<string>("");
  const contracts = useContracts();
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(()=>{ bottomRef.current?.scrollIntoView({behavior:"smooth"}); },[msgs]);

  const send = async (text: string) => {
    if(!text.trim()||loading) return;
    setMsgs(p=>[...p,{id:Date.now().toString(),role:"user",content:text}]);
    setInput(""); setLoading(true);
    try {
      const { userEmail } = useAuthStore.getState();
      let res;
      try { res = await apiClient.post("/api/v1/chat",{
        query:text, session_id:sessionId,
        contract_ids: selectedContractId ? [selectedContractId] : [],
        contract_id: selectedContractId || null,
        user_context: userEmail || undefined
      }); }
      catch { res = await apiClient.post("/api/v1/chat",{
        query:        text,
        session_id:   sessionId,
        contract_ids: selectedContractId ? [selectedContractId] : [],
        contract_id:  selectedContractId || null,
      }); }
      const d = res.data;
      setMsgs(p=>[...p,{id:Date.now()+"a",role:"assistant",content:d.answer||d.message||"No answer found.",citations:d.citations||d.sources}]);
    } catch(err) {
      setMsgs(p=>[...p,{id:Date.now()+"e",role:"assistant",content:getErrorMessage(err),isError:true}]);
    } finally { setLoading(false); }
  };

  return (
    <div style={{ height:"100vh", display:"flex", flexDirection:"column", background:"#f1f5f9" }}>
      <Nav/>
      <div style={{ flex:1, overflowY:"auto", padding:"1.5rem", maxWidth:860, width:"100%", margin:"0 auto" }}>
        {msgs.map(m=>(
          <div key={m.id} style={{ marginBottom:"1.25rem", display:"flex", justifyContent:m.role==="user"?"flex-end":"flex-start" }}>
            {m.role==="assistant"&&<div style={{ width:32, height:32, borderRadius:"50%", background:"#4f46e5", display:"flex", alignItems:"center", justifyContent:"center", flexShrink:0, marginRight:10, marginTop:4 }}><span style={{ color:"#fff", fontSize:14 }}>⚖</span></div>}
            <div style={{ maxWidth:"75%" }}>
              <div style={{ padding:"0.875rem 1.125rem", borderRadius:m.role==="user"?"16px 16px 4px 16px":"16px 16px 16px 4px", background:m.role==="user"?"#4f46e5":m.isError?"#fef2f2":"#fff", color:m.role==="user"?"#fff":m.isError?"#dc2626":"#374151", fontSize:"0.875rem", lineHeight:1.6, boxShadow:"0 1px 4px rgba(0,0,0,0.06)" }}>
                {m.role==="assistant" ? formatMessage(m.content) : m.content}
              </div>
              {m.citations&&m.citations.length>0&&(
                <div style={{ marginTop:6, display:"flex", flexWrap:"wrap", gap:4 }}>
                  {m.citations.slice(0,4).map(c=>(
                    <span key={c.index} style={{ fontSize:"0.7rem", background:"#ede9fe", color:"#6d28d9", padding:"2px 8px", borderRadius:10 }}>
                      [{c.index}] {(c.section_path||c.clause_type||"").split(">").pop()?.trim()}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        {loading&&<div style={{ display:"flex", alignItems:"center", gap:10, marginBottom:"1rem" }}>
          <div style={{ width:32, height:32, borderRadius:"50%", background:"#4f46e5", display:"flex", alignItems:"center", justifyContent:"center" }}><span style={{ color:"#fff", fontSize:14 }}>⚖</span></div>
          <div style={{ background:"#fff", padding:"0.875rem 1.125rem", borderRadius:"16px 16px 16px 4px", boxShadow:"0 1px 4px rgba(0,0,0,0.06)" }}><span style={{ color:"#94a3b8", fontSize:"0.875rem" }}>Analysing…</span></div>
        </div>}
        <div ref={bottomRef}/>
      </div>
      {/* Contract selector */}
      <div style={{ maxWidth:860, width:"100%", margin:"0 auto", padding:"0.5rem 1.5rem" }}>
        <div style={{ display:"flex", alignItems:"center", gap:8 }}>
          <span style={{ fontSize:"0.8rem", color:"#64748b", fontWeight:500, whiteSpace:"nowrap" }}>
            Searching:
          </span>
          <select
            value={selectedContractId}
            onChange={e => {
              setSelectedContractId(e.target.value);
              if (e.target.value) loadHistory(e.target.value);
            }}
            style={{ flex:1, padding:"6px 10px", border:"1px solid #e2e8f0", borderRadius:8,
                     fontSize:"0.8rem", color:"#374151", background:"#fff", cursor:"pointer" }}>
            <option value="">All contracts</option>
            {contracts.map(c => (
              <option key={c.id} value={c.id}>{c.title}</option>
            ))}
          </select>
          {selectedContractId && (
            <button onClick={() => setSelectedContractId("")}
              style={{ background:"none", border:"none", color:"#94a3b8", cursor:"pointer", fontSize:"0.8rem" }}>
              ✕ Clear
            </button>
          )}
        </div>
      </div>
      {msgs.length<=1&&(
        <div style={{ maxWidth:860, width:"100%", margin:"0 auto", padding:"0 1.5rem", display:"flex", gap:8, flexWrap:"wrap" }}>
          {SUGGESTED.map(s=><button key={s} onClick={()=>send(s)} style={{ background:"#fff", border:"1px solid #e2e8f0", borderRadius:20, padding:"6px 14px", fontSize:"0.8rem", color:"#475569", cursor:"pointer" }}>{s}</button>)}
        </div>
      )}
      <div style={{ background:"#fff", borderTop:"1px solid #e2e8f0", padding:"1rem 1.5rem" }}>
        <div style={{ maxWidth:860, margin:"0 auto", display:"flex", gap:8 }}>
          <input value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>e.key==="Enter"&&!e.shiftKey&&send(input)}
            placeholder="Ask about liability caps, renewal dates, payment terms…" disabled={loading}
            style={{ flex:1, padding:"0.75rem 1rem", border:"1px solid #e2e8f0", borderRadius:10, fontSize:"0.875rem", outline:"none" }} />
          <button onClick={()=>send(input)} disabled={!input.trim()||loading}
            style={{ background:input.trim()&&!loading?"#4f46e5":"#e2e8f0", color:input.trim()&&!loading?"#fff":"#94a3b8", border:"none", borderRadius:10, padding:"0 1.25rem", fontSize:"0.875rem", fontWeight:600, cursor:input.trim()&&!loading?"pointer":"not-allowed" }}>
            Send
          </button>
        </div>
        <p style={{ textAlign:"center", fontSize:"0.7rem", color:"#94a3b8", marginTop:8, marginBottom:0 }}>Read-only · Decision support only · Verify with your legal team</p>
      </div>
    </div>
  );
}

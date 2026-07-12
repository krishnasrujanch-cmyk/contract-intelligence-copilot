import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { apiClient, getErrorMessage } from "@/services/api";

interface User { id:string; full_name:string; email:string; role:string; is_active:boolean; last_login:string|null; created_at:string; }
interface Contract { id:string; title:string; status:string; overall_risk:string|null; }
interface Assignment { user_id:string; contract_id:string; }

const RC: Record<string,string> = { admin:"#dc2626", reviewer:"#d97706", viewer:"#16a34a" };
const RK: Record<string,string> = { critical:"#dc2626", high:"#ea580c", medium:"#d97706", low:"#16a34a" };

function Nav() {
  const { logout } = useAuthStore(); const navigate = useNavigate();
  return (
    <nav style={{ background:"#fff", borderBottom:"1px solid #e2e8f0", padding:"0 2rem", display:"flex", alignItems:"center", justifyContent:"space-between", height:56 }}>
      <div style={{ display:"flex", alignItems:"center", gap:12 }}><span style={{ fontSize:20 }}>⚖</span><span style={{ fontWeight:700, color:"#0f172a" }}>Contract Intelligence</span></div>
      <div style={{ display:"flex", gap:"1.5rem", alignItems:"center" }}>
        {["Dashboard","Contracts","Chat","Users"].map(l=>(
          <button key={l} onClick={()=>navigate("/"+( l==="Dashboard"?"":l.toLowerCase()))} style={{ background:"none", border:"none", color:l==="Users"?"#4f46e5":"#475569", fontSize:"0.875rem", cursor:"pointer", fontWeight:l==="Users"?700:500 }}>{l}</button>
        ))}
        <button onClick={async()=>{await logout();navigate("/login");}} style={{ background:"none", border:"1px solid #e2e8f0", borderRadius:8, padding:"4px 12px", fontSize:"0.75rem", color:"#64748b", cursor:"pointer" }}>Sign out</button>
      </div>
    </nav>
  );
}

export default function UsersPage() {
  const { role } = useAuthStore(); const navigate = useNavigate();
  const [users, setUsers] = useState<User[]>([]);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(""); const [success, setSuccess] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [selectedUser, setSelectedUser] = useState<User|null>(null);
  const [selectedContracts, setSelectedContracts] = useState<string[]>([]);
  const [assigning, setAssigning] = useState(false);

  const reload = () => Promise.all([
    apiClient.get("/api/v1/users"),
    apiClient.get("/api/v1/contracts"),
    apiClient.get("/api/v1/users/assignments").catch(()=>({data:[]})),
  ]).then(([u,c,a])=>{ setUsers(u.data); setContracts(c.data); setAssignments(a.data||[]); })
    .catch(e=>setError(getErrorMessage(e))).finally(()=>setLoading(false));

  useEffect(()=>{ if(role!=="admin"){navigate("/");return;} reload(); },[role]);

  const openModal = (u: User) => {
    setSelectedUser(u);
    setSelectedContracts(assignments.filter(a=>a.user_id===u.id).map(a=>a.contract_id));
    setShowModal(true); setError(""); setSuccess("");
  };

  const save = async () => {
    if(!selectedUser) return;
    setAssigning(true); setError("");
    try {
      await apiClient.post("/api/v1/users/"+selectedUser.id+"/assignments", { contract_ids: selectedContracts });
      await reload();
      setSuccess("Assignments updated for "+selectedUser.full_name);
      setShowModal(false);
    } catch(e) { setError(getErrorMessage(e)); }
    finally { setAssigning(false); }
  };

  const count = (uid: string) => assignments.filter(a=>a.user_id===uid).length;
  if(role!=="admin") return null;

  return (
    <div style={{ minHeight:"100vh", background:"#f1f5f9" }}>
      <Nav/>
      <div style={{ maxWidth:1100, margin:"0 auto", padding:"2rem" }}>
        <h1 style={{ fontSize:"1.5rem", fontWeight:700, color:"#0f172a", marginBottom:"1.5rem" }}>User Management</h1>
        {error&&<div style={{ background:"#fef2f2", border:"1px solid #fecaca", borderRadius:8, padding:"0.75rem 1rem", color:"#dc2626", marginBottom:"1rem" }}>{error}</div>}
        {success&&<div style={{ background:"#f0fdf4", border:"1px solid #bbf7d0", borderRadius:8, padding:"0.75rem 1rem", color:"#16a34a", marginBottom:"1rem" }}>{success}</div>}

        <div style={{ background:"#fff", borderRadius:12, boxShadow:"0 1px 4px rgba(0,0,0,0.06)", overflow:"hidden", marginBottom:"1.5rem" }}>
          <div style={{ padding:"1rem 1.5rem", borderBottom:"1px solid #f1f5f9" }}>
            <h2 style={{ fontSize:"1rem", fontWeight:600, color:"#0f172a", margin:0 }}>Users ({users.length})</h2>
          </div>
          {loading?<div style={{ padding:"3rem", textAlign:"center", color:"#94a3b8" }}>Loading…</div>
          :<table style={{ width:"100%", borderCollapse:"collapse" }}>
            <thead><tr style={{ background:"#f8fafc" }}>{["Name","Email","Role","Status","Assigned Contracts","Last Login","Actions"].map(h=>(
              <th key={h} style={{ padding:"0.75rem 1.25rem", textAlign:"left", fontSize:"0.75rem", fontWeight:600, color:"#64748b", textTransform:"uppercase" }}>{h}</th>
            ))}</tr></thead>
            <tbody>{users.map(u=>(
              <tr key={u.id} style={{ borderTop:"1px solid #f1f5f9" }}>
                <td style={{ padding:"1rem 1.25rem", fontSize:"0.875rem", fontWeight:500, color:"#0f172a" }}>{u.full_name}</td>
                <td style={{ padding:"1rem 1.25rem", fontSize:"0.8rem", color:"#64748b" }}>{u.email}</td>
                <td style={{ padding:"1rem 1.25rem" }}><span style={{ background:(RC[u.role]||"#64748b")+"20", color:RC[u.role]||"#64748b", padding:"2px 10px", borderRadius:20, fontSize:"0.75rem", fontWeight:600 }}>{u.role}</span></td>
                <td style={{ padding:"1rem 1.25rem" }}><span style={{ background:u.is_active?"#f0fdf4":"#fef2f2", color:u.is_active?"#16a34a":"#dc2626", padding:"2px 10px", borderRadius:20, fontSize:"0.75rem", fontWeight:600 }}>{u.is_active?"Active":"Inactive"}</span></td>
                <td style={{ padding:"1rem 1.25rem" }}>
                  {u.role==="reviewer"?<span style={{ background:"#ede9fe", color:"#6d28d9", padding:"2px 10px", borderRadius:20, fontSize:"0.75rem", fontWeight:600 }}>{count(u.id)} contract{count(u.id)!==1?"s":""}</span>
                  :<span style={{ color:"#94a3b8", fontSize:"0.8rem" }}>{u.role==="admin"?"All (admin)":"Summary only"}</span>}
                </td>
                <td style={{ padding:"1rem 1.25rem", fontSize:"0.8rem", color:"#64748b" }}>{u.last_login?new Date(u.last_login).toLocaleDateString():"Never"}</td>
                <td style={{ padding:"1rem 1.25rem" }}>
                  {(u.role==="reviewer"||u.role==="viewer")&&<button onClick={()=>openModal(u)} style={{ background:"#4f46e5", color:"#fff", border:"none", borderRadius:6, padding:"5px 12px", fontSize:"0.75rem", fontWeight:600, cursor:"pointer" }}>Assign Contracts</button>}
                </td>
              </tr>
            ))}</tbody>
          </table>}
        </div>

        <div style={{ background:"#fff", borderRadius:12, padding:"1.25rem 1.5rem", boxShadow:"0 1px 4px rgba(0,0,0,0.06)" }}>
          <h3 style={{ fontSize:"0.875rem", fontWeight:600, color:"#374151", marginBottom:"0.75rem" }}>Role Permissions</h3>
          <div style={{ display:"flex", gap:"1rem", flexWrap:"wrap" }}>
            {[
              {role:"admin",color:"#dc2626",desc:"Upload contracts, manage users, assign reviewers, view all data"},
              {role:"reviewer",color:"#d97706",desc:"Upload + view assigned contracts only, submit feedback"},
              {role:"viewer",color:"#16a34a",desc:"View contract summaries only, read-only chat"},
            ].map(r=>(
              <div key={r.role} style={{ flex:1, minWidth:200, padding:"0.75rem", background:"#f8fafc", borderRadius:8 }}>
                <span style={{ background:r.color+"20", color:r.color, padding:"2px 10px", borderRadius:20, fontSize:"0.75rem", fontWeight:600 }}>{r.role}</span>
                <p style={{ fontSize:"0.8rem", color:"#64748b", margin:"0.5rem 0 0" }}>{r.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Assignment Modal */}
      {showModal&&selectedUser&&(
        <div style={{ position:"fixed", inset:0, background:"rgba(0,0,0,0.5)", display:"flex", alignItems:"center", justifyContent:"center", zIndex:50 }}>
          <div style={{ background:"#fff", borderRadius:16, padding:"2rem", width:"100%", maxWidth:520, boxShadow:"0 20px 60px rgba(0,0,0,0.2)", maxHeight:"80vh", display:"flex", flexDirection:"column" }}>
            <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:"1.5rem" }}>
              <div>
                <h2 style={{ fontSize:"1.125rem", fontWeight:700, color:"#0f172a", margin:0 }}>Assign Contracts</h2>
                <p style={{ color:"#64748b", fontSize:"0.875rem", margin:"4px 0 0" }}>{selectedUser.full_name} ({selectedUser.email})</p>
              </div>
              <button onClick={()=>setShowModal(false)} style={{ background:"none", border:"none", fontSize:"1.25rem", cursor:"pointer", color:"#94a3b8" }}>✕</button>
            </div>
            {error&&<div style={{ background:"#fef2f2", border:"1px solid #fecaca", borderRadius:8, padding:"0.75rem", color:"#dc2626", fontSize:"0.875rem", marginBottom:"1rem" }}>{error}</div>}
            <p style={{ fontSize:"0.8rem", color:"#64748b", marginBottom:"1rem" }}>Select contracts this reviewer can access. Saving replaces all existing assignments.</p>
            <div style={{ flex:1, overflowY:"auto", marginBottom:"1.5rem", border:"1px solid #e2e8f0", borderRadius:8, overflow:"hidden" }}>
              {contracts.length===0?<div style={{ padding:"2rem", textAlign:"center", color:"#94a3b8" }}>No contracts available</div>
              :contracts.map((c,i)=>{
                const sel = selectedContracts.includes(c.id);
                return (
                  <div key={c.id} onClick={()=>setSelectedContracts(p=>p.includes(c.id)?p.filter(x=>x!==c.id):[...p,c.id])}
                    style={{ padding:"0.875rem 1rem", display:"flex", alignItems:"center", gap:"0.875rem", cursor:"pointer",
                             borderTop:i>0?"1px solid #f1f5f9":"none", background:sel?"#ede9fe":"#fff", transition:"background 0.15s" }}>
                    <div style={{ width:20, height:20, borderRadius:4, flexShrink:0, border:sel?"2px solid #4f46e5":"2px solid #d1d5db", background:sel?"#4f46e5":"#fff", display:"flex", alignItems:"center", justifyContent:"center" }}>
                      {sel&&<span style={{ color:"#fff", fontSize:12, fontWeight:700 }}>✓</span>}
                    </div>
                    <div style={{ flex:1 }}>
                      <p style={{ fontSize:"0.875rem", fontWeight:500, color:"#0f172a", margin:0 }}>{c.title}</p>
                      <div style={{ display:"flex", gap:8, marginTop:3 }}>
                        <span style={{ fontSize:"0.7rem", background:c.status==="analyzed"?"#f0fdf4":"#fef9c3", color:c.status==="analyzed"?"#16a34a":"#854d0e", padding:"1px 7px", borderRadius:10 }}>{c.status}</span>
                        {c.overall_risk&&<span style={{ fontSize:"0.7rem", background:(RK[c.overall_risk]||"#94a3b8")+"20", color:RK[c.overall_risk]||"#94a3b8", padding:"1px 7px", borderRadius:10 }}>{c.overall_risk} risk</span>}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
            <div style={{ display:"flex", gap:"0.75rem", justifyContent:"flex-end" }}>
              <button onClick={()=>setShowModal(false)} style={{ padding:"0.625rem 1.25rem", border:"1px solid #e2e8f0", borderRadius:8, background:"#fff", color:"#374151", fontSize:"0.875rem", cursor:"pointer" }}>Cancel</button>
              <button onClick={save} disabled={assigning} style={{ padding:"0.625rem 1.25rem", border:"none", borderRadius:8, background:assigning?"#a5b4fc":"#4f46e5", color:"#fff", fontSize:"0.875rem", fontWeight:600, cursor:assigning?"not-allowed":"pointer" }}>
                {assigning?"Saving…":"Save ("+selectedContracts.length+" selected)"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { apiClient, getErrorMessage } from "@/services/api";

interface User { id:string; full_name:string; role:string; is_active:boolean; last_login:string|null; created_at:string; }
const ROLE_COLOR: Record<string,string> = { admin:"#dc2626", reviewer:"#d97706", viewer:"#16a34a" };

export default function UsersPage() {
  const { role, logout } = useAuthStore(); const navigate = useNavigate();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(()=>{ if(role!=="admin"){navigate("/");return;} apiClient.get("/api/v1/users").then(r=>setUsers(r.data)).catch(e=>setError(getErrorMessage(e))).finally(()=>setLoading(false)); },[role]);
  if(role!=="admin") return null;
  return (
    <div style={{ minHeight:"100vh", background:"#f1f5f9" }}>
      <nav style={{ background:"#fff", borderBottom:"1px solid #e2e8f0", padding:"0 2rem", display:"flex", alignItems:"center", justifyContent:"space-between", height:56 }}>
        <div style={{ display:"flex", alignItems:"center", gap:12 }}><span style={{ fontSize:20 }}>⚖</span><span style={{ fontWeight:700, color:"#0f172a" }}>Contract Intelligence</span></div>
        <div style={{ display:"flex", gap:"1.5rem", alignItems:"center" }}>
          {["Dashboard","Contracts","Chat","Users"].map(l=>(
            <button key={l} onClick={()=>navigate("/"+( l==="Dashboard"?"":l.toLowerCase()))} style={{ background:"none", border:"none", color:l==="Users"?"#4f46e5":"#475569", fontSize:"0.875rem", cursor:"pointer", fontWeight:l==="Users"?700:500 }}>{l}</button>
          ))}
          <button onClick={async()=>{await logout();navigate("/login");}} style={{ background:"none", border:"1px solid #e2e8f0", borderRadius:8, padding:"4px 12px", fontSize:"0.75rem", color:"#64748b", cursor:"pointer" }}>Sign out</button>
        </div>
      </nav>
      <div style={{ maxWidth:1000, margin:"0 auto", padding:"2rem" }}>
        <h1 style={{ fontSize:"1.5rem", fontWeight:700, color:"#0f172a", marginBottom:"1.5rem" }}>User Management</h1>
        {error&&<div style={{ background:"#fef2f2", border:"1px solid #fecaca", borderRadius:8, padding:"0.75rem 1rem", color:"#dc2626", marginBottom:"1rem" }}>{error}</div>}
        <div style={{ background:"#fff", borderRadius:12, boxShadow:"0 1px 4px rgba(0,0,0,0.06)", overflow:"hidden" }}>
          <div style={{ padding:"1rem 1.5rem", borderBottom:"1px solid #f1f5f9" }}>
            <h2 style={{ fontSize:"1rem", fontWeight:600, color:"#0f172a", margin:0 }}>Organisation Users ({users.length})</h2>
          </div>
          {loading?<div style={{ padding:"3rem", textAlign:"center", color:"#94a3b8" }}>Loading…</div>
          :<table style={{ width:"100%", borderCollapse:"collapse" }}>
            <thead><tr style={{ background:"#f8fafc" }}>{["Name","Role","Status","Last Login","Created"].map(h=>(
              <th key={h} style={{ padding:"0.75rem 1.5rem", textAlign:"left", fontSize:"0.75rem", fontWeight:600, color:"#64748b", textTransform:"uppercase" }}>{h}</th>
            ))}</tr></thead>
            <tbody>{users.map(u=>(
              <tr key={u.id} style={{ borderTop:"1px solid #f1f5f9" }}>
                <td style={{ padding:"1rem 1.5rem", fontSize:"0.875rem", fontWeight:500, color:"#0f172a" }}>{u.full_name}</td>
                <td style={{ padding:"1rem 1.5rem" }}><span style={{ background:(ROLE_COLOR[u.role]||"#64748b")+"20", color:ROLE_COLOR[u.role]||"#64748b", padding:"2px 10px", borderRadius:20, fontSize:"0.75rem", fontWeight:600 }}>{u.role}</span></td>
                <td style={{ padding:"1rem 1.5rem" }}><span style={{ background:u.is_active?"#f0fdf4":"#fef2f2", color:u.is_active?"#16a34a":"#dc2626", padding:"2px 10px", borderRadius:20, fontSize:"0.75rem", fontWeight:600 }}>{u.is_active?"Active":"Inactive"}</span></td>
                <td style={{ padding:"1rem 1.5rem", fontSize:"0.875rem", color:"#64748b" }}>{u.last_login?new Date(u.last_login).toLocaleDateString():"Never"}</td>
                <td style={{ padding:"1rem 1.5rem", fontSize:"0.875rem", color:"#64748b" }}>{new Date(u.created_at).toLocaleDateString()}</td>
              </tr>
            ))}</tbody>
          </table>}
        </div>
      </div>
    </div>
  );
}

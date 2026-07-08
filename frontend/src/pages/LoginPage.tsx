import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { getErrorMessage } from "@/services/api";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const { login, isLoading } = useAuthStore();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault(); setError("");
    try { await login(email, password); navigate("/"); }
    catch (err) { setError(getErrorMessage(err)); }
  };

  return (
    <div style={{ minHeight:"100vh", display:"flex", alignItems:"center", justifyContent:"center", background:"#f1f5f9" }}>
      <div style={{ background:"#fff", borderRadius:12, padding:"2.5rem", width:"100%", maxWidth:420, boxShadow:"0 4px 24px rgba(0,0,0,0.08)" }}>
        <div style={{ textAlign:"center", marginBottom:"2rem" }}>
          <div style={{ width:48, height:48, borderRadius:12, background:"#4f46e5", margin:"0 auto 1rem", display:"flex", alignItems:"center", justifyContent:"center" }}>
            <span style={{ color:"#fff", fontSize:22 }}>⚖</span>
          </div>
          <h1 style={{ fontSize:"1.5rem", fontWeight:700, color:"#0f172a", margin:0 }}>Contract Intelligence</h1>
          <p style={{ color:"#64748b", marginTop:4, fontSize:"0.875rem" }}>AI-powered contract analysis</p>
        </div>
        {error && <div style={{ background:"#fef2f2", border:"1px solid #fecaca", borderRadius:8, padding:"0.75rem 1rem", color:"#dc2626", fontSize:"0.875rem", marginBottom:"1rem" }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom:"1rem" }}>
            <label style={{ display:"block", fontSize:"0.875rem", fontWeight:500, color:"#374151", marginBottom:6 }}>Email</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} required placeholder="admin@clm.demo"
              style={{ width:"100%", padding:"0.625rem 0.875rem", border:"1px solid #d1d5db", borderRadius:8, fontSize:"0.875rem", outline:"none", boxSizing:"border-box" }} />
          </div>
          <div style={{ marginBottom:"1.5rem" }}>
            <label style={{ display:"block", fontSize:"0.875rem", fontWeight:500, color:"#374151", marginBottom:6 }}>Password</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} required placeholder="••••••••"
              style={{ width:"100%", padding:"0.625rem 0.875rem", border:"1px solid #d1d5db", borderRadius:8, fontSize:"0.875rem", outline:"none", boxSizing:"border-box" }} />
          </div>
          <button type="submit" disabled={isLoading}
            style={{ width:"100%", padding:"0.75rem", background:isLoading?"#a5b4fc":"#4f46e5", color:"#fff", border:"none", borderRadius:8, fontSize:"0.875rem", fontWeight:600, cursor:isLoading?"not-allowed":"pointer" }}>
            {isLoading ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <div style={{ marginTop:"1.5rem", padding:"1rem", background:"#f8fafc", borderRadius:8, fontSize:"0.75rem", color:"#64748b" }}>
          <strong>Demo credentials:</strong><br/>
          admin@clm.demo / Admin@Demo2026!<br/>
          reviewer@clm.demo / Review@Demo2026!<br/>
          viewer@clm.demo / View@Demo2026!
        </div>
      </div>
    </div>
  );
}

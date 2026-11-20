import React, { useEffect, useState } from "react";

// Plain on purpose (the brief: "a plain table is the correct answer").
// All filtering happens in the API; this component only renders what it gets.

function csrfToken() {
  const m = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/);
  return m ? decodeURIComponent(m[1]) : "";
}

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(`/api/${path}`, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json", "X-CSRFToken": csrfToken() } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({ error: `Server error (${res.status})` }));
  return { ok: res.ok, status: res.status, data };
}

const s = {
  page: { fontFamily: "system-ui, sans-serif", margin: "16px", color: "#111", background: "#fff" },
  table: { borderCollapse: "collapse", width: "100%", fontSize: 14 },
  cell: { border: "1px solid #ccc", padding: "4px 6px", verticalAlign: "top", textAlign: "left" },
  num: { border: "1px solid #ccc", padding: "4px 6px", verticalAlign: "top", textAlign: "right", whiteSpace: "nowrap" },
  error: { color: "#b00020" },
};

function money(v) {
  return v == null ? "—" : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2 });
}

function Login({ onLogin }) {
  const [username, setUsername] = useState("alice");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setError("");
    const r = await api("login", { method: "POST", body: { username, password } });
    if (r.ok) onLogin(r.data);
    else setError(r.data.error || "Login failed");
  }

  return (
    <form onSubmit={submit}>
      <h1>DealerOS exceptions</h1>
      <p>Demo users: alice / alice-pass (ORG-A), bob / bob-pass (ORG-B).</p>
      <label>Username <input value={username} onChange={(e) => setUsername(e.target.value)} /></label>{" "}
      <label>Password <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>{" "}
      <button type="submit">Log in</button>
      {error && <p style={s.error}>{error}</p>}
    </form>
  );
}

function Ask() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState(null);

  async function submit(e) {
    e.preventDefault();
    const r = await api("ask", { method: "POST", body: { question } });
    setResult(r.ok ? r.data : { answered: false, answer: r.data.error });
  }

  return (
    <form onSubmit={submit} style={{ margin: "16px 0" }}>
      <label>
        Ask about all your organisation's exceptions{" "}
        <input
          style={{ width: "28em", maxWidth: "100%" }}
          value={question}
          placeholder="e.g. How many duplicates? / total amount difference at LOC-101"
          onChange={(e) => setQuestion(e.target.value)}
        />
      </label>{" "}
      <button type="submit">Ask</button>
      {result && (
        <pre style={{ whiteSpace: "pre-wrap", background: result.answered ? "#f3f7f3" : "#fff4f4", padding: 8 }}>
          {result.answered ? "" : "Not answered. "}
          {result.answer}
        </pre>
      )}
    </form>
  );
}

function Exceptions({ me, onLogout }) {
  const [reason, setReason] = useState("");
  const [location, setLocation] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const q = new URLSearchParams();
    if (reason) q.set("reason_code", reason);
    if (location) q.set("location_id", location);
    api(`exceptions?${q}`).then((r) => {
      if (r.ok) { setData(r.data); setError(""); }
      else if (r.status === 401) onLogout();
      else setError(r.data.error || "Could not load exceptions");
    });
  }, [reason, location]);

  async function logout() {
    await api("logout", { method: "POST", body: {} });
    onLogout();
  }

  return (
    <div>
      <p>
        Logged in as <b>{me.username}</b> ({me.org_id}) <button onClick={logout}>Log out</button>
      </p>
      <h1>Records the two systems disagree about</h1>
      {error && <p style={s.error}>{error}</p>}
      {data && (
        <>
          <label>
            Reason{" "}
            <select value={reason} onChange={(e) => setReason(e.target.value)}>
              <option value="">All reasons</option>
              {data.filters.reason_codes.map((r) => (
                <option key={r.code} value={r.code}>{r.label}</option>
              ))}
            </select>
          </label>{" "}
          <label>
            Location{" "}
            <select value={location} onChange={(e) => setLocation(e.target.value)}>
              <option value="">All locations</option>
              {data.filters.locations.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
          </label>{" "}
          <span>{data.count} shown</span>
          <Ask />
          <div style={{ overflowX: "auto" }}>
            <table style={s.table}>
              <thead>
                <tr>
                  {["Record (System A)", "Entries (System B)", "Location", "Date", "Problem", "What to do",
                    "System A amount", "System B amount", "Details"].map((h) => (
                    <th key={h} style={s.cell}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.results.map((r) => (
                  <tr key={r.id}>
                    <td style={s.cell}>{r.record_id || "—"}</td>
                    <td style={s.cell}>{r.entry_ids.join(", ") || "—"}</td>
                    <td style={s.cell}>{r.location_id}</td>
                    <td style={s.cell}>{r.event_date || "—"}</td>
                    <td style={s.cell} title={r.reason_code}>{r.reason}</td>
                    <td style={s.cell}>{r.action}</td>
                    <td style={s.num}>{money(r.system_a_amount)}</td>
                    <td style={s.num}>{money(r.system_b_amount)}</td>
                    <td style={s.cell}>{r.detail}</td>
                  </tr>
                ))}
                {data.results.length === 0 && (
                  <tr><td style={s.cell} colSpan={9}>No exceptions match these filters.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

export default function App() {
  const [me, setMe] = useState(undefined); // undefined = loading, null = logged out

  useEffect(() => {
    api("csrf").then(() => api("me")).then((r) => setMe(r.ok ? r.data : null));
  }, []);

  return (
    <div style={s.page}>
      {me === undefined ? <p>Loading…</p>
        : me ? <Exceptions me={me} onLogout={() => setMe(null)} />
        : <Login onLogin={setMe} />}
    </div>
  );
}

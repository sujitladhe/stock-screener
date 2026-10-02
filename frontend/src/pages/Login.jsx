import { useState } from "react";
import { login } from "../api";

function BrandMark() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
      <rect width="28" height="28" rx="8" fill="var(--text)" />
      <rect x="6" y="15" width="3.6" height="7" rx="1.2" fill="var(--ground)" />
      <rect x="12.2" y="11" width="3.6" height="11" rx="1.2" fill="var(--ground)" />
      <rect x="18.4" y="6" width="3.6" height="16" rx="1.2" fill="var(--mari)" />
    </svg>
  );
}

export default function Login({ onLoggedIn }) {
  const [form, setForm] = useState({
    app_key: "",
    app_secret: "",
    client_id: "",
    pin: "",
    totp_secret: "",
  });
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  function update(field) {
    return (e) => setForm((f) => ({ ...f, [field]: e.target.value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await login(form);
      onLoggedIn(result.client_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login">
      <div className="login-art">
        <span className="brand"><BrandMark />Screener</span>
        <div>
          <h2>See the volume surge as it happens.</h2>
          <p>Every NSE stock, checked minute by minute, with your orders one tap away.</p>
        </div>
        <p className="muted small">Trades are placed only through your own Ventura account.</p>
      </div>
      <div className="login-form">
        <form onSubmit={handleSubmit}>
          <h1>Sign in</h1>
          <p className="muted">Enter your Ventura API credentials.</p>

          <Field label="App key" value={form.app_key} onChange={update("app_key")} />
          <Field label="App secret" value={form.app_secret} onChange={update("app_secret")} type="password" />
          <Field label="Client ID" value={form.client_id} onChange={update("client_id")} />
          <Field label="PIN" value={form.pin} onChange={update("pin")} type="password" />
          <Field label="TOTP secret" value={form.totp_secret} onChange={update("totp_secret")} type="password" hint="The authenticator secret key, not the 6-digit code." />

          {error && <div className="err" role="alert">{error}</div>}

          <button type="submit" className="btn primary wide" disabled={submitting} style={{ marginTop: 6 }}>
            {submitting ? "Signing in..." : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, type = "text", hint }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input className="input" type={type} value={value} onChange={onChange} required />
      {hint && <span className="hint">{hint}</span>}
    </label>
  );
}

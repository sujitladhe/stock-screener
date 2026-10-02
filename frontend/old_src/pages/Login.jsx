import { useState } from "react";
import { login } from "../api";

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
    <div style={styles.page}>
      <form style={styles.card} onSubmit={handleSubmit}>
        <h1 style={styles.title}>Sign in</h1>
        <p style={styles.subtitle}>Enter your Ventura API credentials.</p>

        <Field label="App key" value={form.app_key} onChange={update("app_key")} />
        <Field label="App secret" value={form.app_secret} onChange={update("app_secret")} type="password" />
        <Field label="Client ID" value={form.client_id} onChange={update("client_id")} />
        <Field label="PIN" value={form.pin} onChange={update("pin")} type="password" />
        <Field
          label="TOTP secret"
          value={form.totp_secret}
          onChange={update("totp_secret")}
          type="password"
          hint="The authenticator secret key, not the 6-digit code."
        />

        {error && <div style={styles.error}>{error}</div>}

        <button type="submit" disabled={submitting} style={styles.submit}>
          {submitting ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </div>
  );
}

function Field({ label, value, onChange, type = "text", hint }) {
  return (
    <label style={styles.field}>
      <span style={styles.label}>{label}</span>
      <input type={type} value={value} onChange={onChange} required style={styles.input} />
      {hint && <span style={styles.hint}>{hint}</span>}
    </label>
  );
}

const styles = {
  page: {
    minHeight: "100%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 20,
  },
  card: {
    width: 360,
    display: "flex",
    flexDirection: "column",
    gap: 14,
  },
  title: {
    fontSize: 20,
    fontWeight: 600,
    margin: 0,
  },
  subtitle: {
    fontSize: 13,
    color: "var(--text-muted)",
    margin: "0 0 8px 0",
  },
  field: {
    display: "flex",
    flexDirection: "column",
    gap: 4,
  },
  label: {
    fontSize: 12,
    color: "var(--text-muted)",
  },
  input: {
    padding: "9px 12px",
  },
  hint: {
    fontSize: 11,
    color: "var(--text-muted)",
  },
  error: {
    fontSize: 13,
    color: "var(--negative)",
    background: "rgba(255, 92, 92, 0.1)",
    border: "1px solid rgba(255, 92, 92, 0.3)",
    borderRadius: 6,
    padding: "8px 12px",
  },
  submit: {
    marginTop: 6,
    background: "var(--focus)",
    borderColor: "var(--focus)",
    color: "#fff",
  },
};

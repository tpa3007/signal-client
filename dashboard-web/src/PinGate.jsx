import React, { useEffect, useState } from "react";

// Default PIN is 4827. Override at build time with a Vercel env var
// VITE_PIN_SHA256 = sha256(yourPin). This is a light client-side gate — it
// keeps casual visitors out, not a determined attacker (the hash ships in the
// bundle). For hard protection use Vercel Deployment Protection.
const DEFAULT_PIN_SHA256 = "f16592d12000ffca0f1159286959f4c2470c82a7b48940020b1323a6d49abe27";
const EXPECTED = (import.meta.env.VITE_PIN_SHA256 || DEFAULT_PIN_SHA256).toLowerCase();
const STORAGE_KEY = "signal-pin-ok";

async function sha256(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function PinGate({ children }) {
  const [unlocked, setUnlocked] = useState(false);
  const [checked, setChecked] = useState(false);
  const [pin, setPin] = useState("");
  const [error, setError] = useState(false);

  useEffect(() => {
    setUnlocked(sessionStorage.getItem(STORAGE_KEY) === EXPECTED ||
                localStorage.getItem(STORAGE_KEY) === EXPECTED);
    setChecked(true);
  }, []);

  async function submit(event) {
    event.preventDefault();
    const hash = await sha256(pin.trim());
    if (hash === EXPECTED) {
      localStorage.setItem(STORAGE_KEY, EXPECTED);
      setUnlocked(true);
      setError(false);
    } else {
      setError(true);
      setPin("");
    }
  }

  if (!checked) return null;
  if (unlocked) return children;

  return (
    <div className="pin-gate">
      <form className="pin-card" onSubmit={submit}>
        <span className="pin-kicker">SIGNAL · PRIVATE</span>
        <h1>Введите пинкод</h1>
        <p>Доступ к портфелю и аналитике ограничен.</p>
        <input
          type="password"
          inputMode="numeric"
          autoFocus
          value={pin}
          onChange={(e) => { setPin(e.target.value); setError(false); }}
          placeholder="••••"
          className={error ? "error" : ""}
          aria-label="PIN"
        />
        {error && <span className="pin-error">Неверный пинкод</span>}
        <button type="submit">Войти</button>
      </form>
    </div>
  );
}

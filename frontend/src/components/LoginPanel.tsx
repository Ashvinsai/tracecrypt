import { Lock } from "lucide-react";
import { useState } from "react";
import { useLogin } from "../lib/auth";
import { inputStyle } from "../lib/styles";
import { Callout, Panel } from "./ui";

/** Session sign-in for the case-database sections. Demo credentials are local. */
export function LoginPanel({ intro }: { intro: string }) {
  const login = useLogin();
  const [email, setEmail] = useState("investigator@example.test");
  const [password, setPassword] = useState("");

  return (
    <Panel title="Sign in to the case database">
      <div className="stack lg" style={{ maxWidth: 460 }}>
        <Callout icon={Lock} title="Local case database.">
          {intro}
        </Callout>
        <form
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            login.mutate({ email, password });
          }}
        >
          <label className="stack" style={{ gap: 4 }}>
            <span className="muted" style={{ fontSize: 11 }}>
              Account
            </span>
            <input
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="username"
              style={inputStyle}
            />
          </label>
          <label className="stack" style={{ gap: 4 }}>
            <span className="muted" style={{ fontSize: 11 }}>
              Password
            </span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              style={inputStyle}
            />
          </label>
          <div className="row">
            <button type="submit" className="btn primary" disabled={login.isPending}>
              {login.isPending ? "Signing in…" : "Sign in"}
            </button>
            <span className="muted" style={{ fontSize: 11 }}>
              Created only by <code>make seed-demo</code>; never in production.
            </span>
          </div>
          {login.isError ? (
            <div className="muted" style={{ color: "var(--danger)", fontSize: 12 }}>
              {(login.error as Error).message}
            </div>
          ) : null}
        </form>
      </div>
    </Panel>
  );
}

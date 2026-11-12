import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, api, onUnauthorized, type AuthMe } from "@/lib/api";
import { Wordmark } from "./Wordmark";

const ME_KEY = ["auth-me"] as const;

const useMe = () => useQuery({ queryKey: ME_KEY, queryFn: api.me, staleTime: Infinity, retry: false });

/** Drop every cached response except the auth state, so nothing private outlives the session. */
function dropData(qc: QueryClient) {
  qc.removeQueries({ predicate: (q) => q.queryKey[0] !== ME_KEY[0] });
}

/**
 * Renders the app only once the visitor may see it. Through the public tunnel that means signed
 * in; on the LAN `login_required` is false and the app renders straight away.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const me = useMe();

  // Any 401 means the session is gone or expired: re-ask the server, which flips us to the login screen.
  useEffect(() => onUnauthorized(() => void qc.invalidateQueries({ queryKey: ME_KEY })), [qc]);

  if (me.isPending) return null;
  const data = me.data;
  if (data?.login_required && !data.authenticated) {
    return (
      <LoginScreen
        onSignedIn={async () => {
          dropData(qc);
          await qc.invalidateQueries({ queryKey: ME_KEY });
        }}
      />
    );
  }
  // If /api/auth/me itself failed (old server, network), fall through: pages show their own errors.
  return <>{children}</>;
}

export function SignOutButton() {
  const qc = useQueryClient();
  const { data } = useMe();
  const [busy, setBusy] = useState(false);
  if (!data?.authenticated) return null;
  return (
    <button
      type="button"
      disabled={busy}
      className="kicker py-1 text-ink-muted underline-offset-[5px] hover:text-ink hover:underline disabled:opacity-40"
      onClick={async () => {
        setBusy(true);
        try {
          await api.logout();
        } catch {
          // even if the request fails, forget the session locally
        }
        dropData(qc);
        qc.setQueryData<AuthMe>(ME_KEY, { ...data, authenticated: false, username: null });
        setBusy(false);
      }}
    >
      Sign out
    </button>
  );
}

function loginError(e: unknown): string {
  if (e instanceof ApiError && e.status === 401) return "Wrong username or password.";
  if (e instanceof ApiError && e.status === 429) return "Too many attempts. Wait 15 minutes and try again.";
  return "Could not sign in. Check your connection and try again.";
}

function LoginScreen({ onSignedIn }: { onSignedIn: () => Promise<void> }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    if (!username.trim() || !password) {
      setError("Enter your username and password.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      await api.login(username.trim(), password);
      setPassword("");
      await onSignedIn();
    } catch (err) {
      setError(loginError(err));
      setPassword("");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex min-h-dvh flex-col bg-paper">
      <header className="border-b-2 border-ink px-5 lg:px-6">
        <div className="flex h-14 items-center">
          <Wordmark />
        </div>
      </header>
      <main id="main" className="flex flex-1 items-start justify-center px-5 pt-[14vh] pb-16">
        <form onSubmit={submit} className="w-full max-w-[22rem]" aria-labelledby="signin-title" noValidate>
          <p className="kicker text-ink-muted">Private workspace</p>
          <h1
            id="signin-title"
            className="display mt-2 border-b border-ink pb-4 text-[34px] leading-none font-[800] tracking-[-0.03em]"
          >
            Sign in
          </h1>
          <div className="mt-6 grid gap-5">
            <div className="grid gap-1.5">
              <label htmlFor="login-username" className="kicker text-ink-muted">
                Username
              </label>
              <Input
                id="login-username"
                name="username"
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                autoFocus
                required
                maxLength={128}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <label htmlFor="login-password" className="kicker text-ink-muted">
                Password
              </label>
              <Input
                id="login-password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                maxLength={1024}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            {error && (
              <p role="alert" className="border-l-2 border-ink bg-chip px-3 py-2 text-sm text-ink">
                {error}
              </p>
            )}
            <Button type="submit" size="lg" disabled={pending} className="w-full">
              {pending ? "Signing in" : "Sign in"}
            </Button>
          </div>
        </form>
      </main>
    </div>
  );
}

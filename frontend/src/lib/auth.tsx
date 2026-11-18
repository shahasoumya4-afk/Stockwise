import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { getSession, setSession, hasPermission, type Session } from "./api";

type Ctx = {
  session: Session | null;
  ready: boolean;
  signIn: (s: Session) => void;
  signOut: () => void;
  can: (perm: string) => boolean;
};
const AuthContext = createContext<Ctx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setS] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const sync = () => setS(getSession());
    sync();
    setReady(true);
    window.addEventListener("irm-session", sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener("irm-session", sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  return (
    <AuthContext.Provider
      value={{
        session,
        ready,
        signIn: (s) => setSession(s),
        signOut: () => setSession(null),
        can: (p) => hasPermission(session?.user, p),
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
export function useAuth() {
  const c = useContext(AuthContext);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}

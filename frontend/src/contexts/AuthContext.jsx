import { createContext, useCallback, useContext, useEffect, useReducer, useRef } from "react";
import {
  GoogleAuthProvider,
  createUserWithEmailAndPassword,
  deleteUser,
  onAuthStateChanged,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
  updateProfile,
} from "firebase/auth";
import { api, formatApiError } from "../lib/api";
import { auth, isFirebaseConfigured } from "../lib/firebase";
import { initialAuthState, reduceAuthAction } from "../lib/authState";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [state, dispatch] = useReducer(
    reduceAuthAction,
    { firebaseConfigured: Boolean(auth && isFirebaseConfigured) },
    initialAuthState,
  );
  const errorRef = useRef("");

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get("/auth/me");
      dispatch({ type: "REFRESH_RESULT", user: data });
      return data;
    } catch {
      dispatch({ type: "REFRESH_RESULT", user: null });
      return null;
    }
  }, []);

  useEffect(() => {
    if (!auth) {
      refresh();
      return undefined;
    }
    let firstFire = true;
    const unsub = onAuthStateChanged(auth, (firebaseUser) => {
      dispatch({ type: "FIREBASE_RESOLVED", firebaseUser });
      if (firebaseUser || firstFire) {
        refresh();
      }
      firstFire = false;
    });
    return unsub;
  }, [refresh]);

  const requireFirebaseAuth = () => {
    if (!auth || !isFirebaseConfigured) {
      throw new Error("Sign-in is unavailable right now.");
    }
  };

  const setError = (msg) => {
    errorRef.current = msg;
  };

  const login = async (email, password) => {
    setError("");
    try {
      requireFirebaseAuth();
      await signInWithEmailAndPassword(auth, email, password);
      const { data } = await api.get("/auth/me");
      dispatch({ type: "REFRESH_RESULT", user: data });
      return data;
    } catch (e) {
      const msg = formatApiError(e.response?.data?.detail) || e.message;
      setError(msg);
      throw new Error(msg);
    }
  };

  const loginWithGoogle = async () => {
    setError("");
    try {
      requireFirebaseAuth();
      const provider = new GoogleAuthProvider();
      provider.addScope("profile");
      provider.addScope("email");
      await signInWithPopup(auth, provider);
      const { data } = await api.get("/auth/me");
      dispatch({ type: "REFRESH_RESULT", user: data });
      return data;
    } catch (e) {
      const msg = formatApiError(e.response?.data?.detail) || e.message;
      setError(msg);
      throw new Error(msg);
    }
  };

  const register = async (payload) => {
    setError("");
    try {
      if (auth && isFirebaseConfigured) {
        const credential = await createUserWithEmailAndPassword(auth, payload.email, payload.password);
        if (payload.name) {
          await updateProfile(credential.user, { displayName: payload.name });
        }
      }
      const { data } = await api.post("/auth/register", payload);
      dispatch({ type: "REFRESH_RESULT", user: data });
      return data;
    } catch (e) {
      if (auth?.currentUser && auth.currentUser.email?.toLowerCase() === payload.email?.toLowerCase()) {
        try { await deleteUser(auth.currentUser); } catch { /* ignore cleanup errors */ }
      }
      const msg = formatApiError(e.response?.data?.detail) || e.message;
      setError(msg);
      throw new Error(msg);
    }
  };

  const registerFull = async (payload) => {
    setError("");
    try {
      if (auth && isFirebaseConfigured) {
        const credential = await createUserWithEmailAndPassword(auth, payload.parent_email, payload.password);
        if (payload.parent_name) {
          await updateProfile(credential.user, { displayName: payload.parent_name });
        }
      }
      const { data } = await api.post("/auth/register-full", payload);
      dispatch({ type: "REFRESH_RESULT", user: data });
      return data;
    } catch (e) {
      if (auth?.currentUser && auth.currentUser.email?.toLowerCase() === payload.parent_email?.toLowerCase()) {
        try { await deleteUser(auth.currentUser); } catch { /* ignore cleanup errors */ }
      }
      const msg = formatApiError(e.response?.data?.detail) || e.message;
      setError(msg);
      throw new Error(msg);
    }
  };

  const logout = async () => {
    try { await api.post("/auth/logout"); } catch { /* ignore */ }
    try { if (auth) await signOut(auth); } catch { /* ignore */ }
    dispatch({ type: "LOGOUT" });
  };

  const resetPassword = async (email) => {
    setError("");
    try {
      requireFirebaseAuth();
      await sendPasswordResetEmail(auth, email);
    } catch (e) {
      const msg = formatApiError(e.response?.data?.detail) || e.message;
      setError(msg);
      throw new Error(msg);
    }
  };

  // Public 'user' contract preserved: null while loading, false when anon, object when authed.
  // This keeps existing route guards (`user === null` → checking, `user` truthy → authed) working.
  const publicUser =
    state.status === "loading" ? null
      : state.status === "authenticated" ? state.user
        : false;

  return (
    <AuthContext.Provider
      value={{
        user: publicUser,
        status: state.status,
        error: errorRef.current,
        login,
        loginWithGoogle,
        register,
        registerFull,
        logout,
        resetPassword,
        refresh,
        setUser: (u) => dispatch({ type: "REFRESH_RESULT", user: u || null }),
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);

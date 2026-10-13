import { create } from "zustand";
import { User } from "@/types";
import { getUser, setUser as saveUser, clearTokens } from "@/lib/auth";

interface AuthState {
  user: User | null;
  isLoading: boolean;
  setUser: (user: User | null) => void;
  logout: () => void;
  loadUser: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isLoading: true,
  setUser: (user) => {
    if (user) {
      saveUser(user);
    }
    set({ user, isLoading: false });
  },
  logout: () => {
    clearTokens();
    set({ user: null });
  },
  loadUser: () => {
    const user = getUser();
    set({ user, isLoading: false });
  },
}));

"use client";

import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  clearAccessToken,
  getAccessToken,
  login as apiLogin,
  logout as apiLogout,
  register as apiRegister,
  subscribeAccessToken,
} from "../auth-client";
import { api, type User } from "../api/client";

type AuthContextValue = {
  user: User | undefined;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName?: string) => Promise<void>;
  logout: () => Promise<void>;
};

import { createContext, useContext } from "react";

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const queryClient = useQueryClient();
  const router = useRouter();

  useEffect(() => {
    setToken(getAccessToken());
    setReady(true);
    return subscribeAccessToken(() => setToken(getAccessToken()));
  }, []);

  const {
    data: user,
    isLoading: userLoading,
    refetch,
  } = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    enabled: Boolean(token),
    retry: false,
  });

  const loginMutation = useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      apiLogin(email, password),
    onSuccess: async () => {
      await refetch();
      router.push("/dashboard");
    },
  });

  const registerMutation = useMutation({
    mutationFn: ({
      email,
      password,
      fullName,
    }: {
      email: string;
      password: string;
      fullName?: string;
    }) => apiRegister(email, password, fullName),
    onSuccess: async (_data, variables) => {
      await apiLogin(variables.email, variables.password);
      await refetch();
      router.push("/dashboard");
    },
  });

  const logoutMutation = useMutation({
    mutationFn: apiLogout,
    onSuccess: () => {
      clearAccessToken();
      queryClient.clear();
      router.push("/login");
    },
  });

  const value: AuthContextValue = {
    user,
    isAuthenticated: Boolean(token),
    isLoading: !ready || (Boolean(token) && userLoading),
    login: useCallback(
      async (email, password) => {
        await loginMutation.mutateAsync({ email, password });
      },
      [loginMutation],
    ),
    register: useCallback(
      async (email, password, fullName) => {
        await registerMutation.mutateAsync({ email, password, fullName });
      },
      [registerMutation],
    ),
    logout: useCallback(async () => {
      await logoutMutation.mutateAsync();
    }, [logoutMutation]),
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

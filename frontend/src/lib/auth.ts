import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export interface SessionUser {
  id: string;
  email: string;
  display_name: string | null;
  organizations: { id: string; name: string; slug: string }[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "content-type": "application/json", accept: "application/json" },
    ...init,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error?.message ?? `request failed: ${response.status}`);
  }
  const envelope = (await response.json()) as { data: T };
  return envelope.data;
}

/** Session state lives on the server; this only reads and refreshes it. */
export function useSession() {
  const query = useQuery<SessionUser | null>({
    queryKey: ["session"],
    queryFn: async () => {
      try {
        return await request<SessionUser>("/api/v1/auth/me");
      } catch {
        return null;
      }
    },
    staleTime: 30_000,
  });
  return query;
}

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (credentials: { email: string; password: string }) =>
      request<{ id: string; email: string }>("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify(credentials),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["session"] }),
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => request<{ logged_out: boolean }>("/api/v1/auth/logout", { method: "POST" }),
    onSuccess: () => client.invalidateQueries(),
  });
}

export interface CaseRecord {
  id: string;
  case_reference: string;
  title: string;
  status: string;
  data_mode: string;
  created_at: string | null;
}

export const caseApi = {
  list: () => request<CaseRecord[]>("/api/v1/cases"),
  create: (payload: { case_reference: string; title: string }) =>
    request<CaseRecord>("/api/v1/cases", { method: "POST", body: JSON.stringify(payload) }),
  validateAddress: (networkKey: string, address: string) =>
    request<{ valid: boolean; canonical_address?: string; reason?: string; network_key: string }>(
      `/api/v1/addresses/validate?network_key=${encodeURIComponent(networkKey)}&address=${encodeURIComponent(address)}`,
    ),
};

export interface WatchRecord {
  id: string;
  case_id: string;
  network_key: string;
  address: string;
  status: string;
  last_checkpoint_at: string | null;
  created_at: string | null;
}

export interface AlertRecord {
  id: string;
  watch_id: string;
  event_reference: string;
  alert_type: string;
  severity: string;
  state: string;
  first_observed_at: string;
  summary: string | null;
  from_address: string | null;
  to_address: string | null;
}

export interface PollRecord {
  id: string;
  status: string;
  coverage_status: string;
  provider: string;
  started_at: string;
  completed_at: string | null;
  new_alerts: number;
  events_observed: number;
  provider_requests: number;
  error_class: string | null;
  error_message: string | null;
}

export const watchApi = {
  list: (caseId: string) => request<WatchRecord[]>(`/api/v1/cases/${caseId}/watches`),
  alerts: (caseId: string, watchId: string) =>
    request<AlertRecord[]>(`/api/v1/cases/${caseId}/watches/${watchId}/alerts`),
  polls: (caseId: string, watchId: string) =>
    request<PollRecord[]>(`/api/v1/cases/${caseId}/watches/${watchId}/polls`),
};

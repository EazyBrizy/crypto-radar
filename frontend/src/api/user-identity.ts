import { DEV_FALLBACK_USER_ID } from "@/auth/current-user";
import { authApi } from "./auth.api";

export async function currentUserId(): Promise<string> {
  const session = await authApi.currentSession();
  return session?.user.id ?? DEV_FALLBACK_USER_ID;
}

export async function currentUserQuery(): Promise<{ user_id: string }> {
  return { user_id: await currentUserId() };
}

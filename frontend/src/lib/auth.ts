const TOKEN_KEY = "comfyui2api.adminToken";

export function getAdminToken(): string {
  return window.sessionStorage.getItem(TOKEN_KEY) ?? "";
}

export function setAdminToken(token: string): void {
  window.sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearAdminToken(): void {
  window.sessionStorage.removeItem(TOKEN_KEY);
}

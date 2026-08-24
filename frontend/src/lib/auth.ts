const TOKEN_KEY = "comfyui2api.adminToken";
const API_TOKEN_KEY = "comfyui2api.apiToken";

export function getAdminToken(): string {
  return window.sessionStorage.getItem(TOKEN_KEY) ?? "";
}

export function setAdminToken(token: string): void {
  window.sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearAdminToken(): void {
  window.sessionStorage.removeItem(TOKEN_KEY);
}

export function getApiToken(): string {
  return window.sessionStorage.getItem(API_TOKEN_KEY) ?? "";
}

export function setApiToken(token: string): void {
  window.sessionStorage.setItem(API_TOKEN_KEY, token);
}

export function clearApiToken(): void {
  window.sessionStorage.removeItem(API_TOKEN_KEY);
}

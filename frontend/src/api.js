// Centralised backend base URL.
// In a Tauri desktop build the WebView origin is not localhost,
// so we always point explicitly at 127.0.0.1 rather than using
// window.location.hostname (which would resolve to the Tauri protocol).
export const BASE_URL = 'http://127.0.0.1:8000'
export const FILES_API = `${BASE_URL}/files`

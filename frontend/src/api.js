// Centralised backend base URL.
// In a Tauri desktop build the WebView origin is a custom protocol (not http),
// so we fall back to 127.0.0.1.  When accessed from a regular browser
// (including phones on the same LAN) we use the page's own hostname so
// that the API is reachable at the correct IP.
const isTauri = typeof window !== 'undefined' && window.__TAURI_INTERNALS__ !== undefined;
const host = isTauri
  ? '127.0.0.1'
  : (typeof window !== 'undefined' ? window.location.hostname : '127.0.0.1');
export const BASE_URL = `http://${host}:8000`
export const FILES_API = `${BASE_URL}/files`

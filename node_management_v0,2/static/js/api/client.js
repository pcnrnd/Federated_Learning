/** API 클라이언트 기본 유틸리티 */
const API_BASE = '';

async function handleResponse(response) {
  if (!response.ok) {
    const error = await response.json().catch(() => ({ 
      detail: response.statusText 
    }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

export async function apiGet(endpoint) {
  return handleResponse(await fetch(`${API_BASE}${endpoint}`));
}

export async function apiPost(endpoint, data) {
  return handleResponse(await fetch(`${API_BASE}${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  }));
}

export async function apiPut(endpoint, data) {
  return handleResponse(await fetch(`${API_BASE}${endpoint}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  }));
}

export async function apiDelete(endpoint) {
  return handleResponse(await fetch(`${API_BASE}${endpoint}`, {
    method: 'DELETE'
  }));
}


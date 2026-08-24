/** 서버 관련 API 호출 */
import { apiGet, apiPost, apiPut, apiDelete } from './client.js';

export async function getNodes() {
  return apiGet('/api/nodes');
}

export async function getNodesStatus() {
  return apiGet('/api/nodes/status');
}

export async function getNode(nodeId) {
  return apiGet(`/api/nodes/${nodeId}`);
}

export async function addNode(serverData) {
  return apiPost('/api/nodes', serverData);
}

export async function updateNode(nodeId, serverData) {
  return apiPut(`/api/nodes/${nodeId}`, serverData);
}

export async function deleteNode(nodeId) {
  return apiDelete(`/api/nodes/${nodeId}`);
}

export async function testConnection(nodeId) {
  return apiPost(`/api/nodes/${nodeId}/test`, {});
}


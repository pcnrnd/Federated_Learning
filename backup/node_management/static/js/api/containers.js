/** 컨테이너 관련 API 호출 */
import { apiGet, apiPost } from './client.js';

export async function getContainers(nodeId, all = true) {
  return apiGet(`/api/containers?node_id=${encodeURIComponent(nodeId)}&all=${all}`);
}

export async function startContainer(nodeId, containerId) {
  return apiPost('/api/containers/start', { node_id: nodeId, container_id: containerId });
}

export async function stopContainer(nodeId, containerId) {
  return apiPost('/api/containers/stop', { node_id: nodeId, container_id: containerId });
}

export async function restartContainer(nodeId, containerId) {
  return apiPost('/api/containers/restart', { node_id: nodeId, container_id: containerId });
}


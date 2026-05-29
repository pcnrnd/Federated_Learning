import { NODE_COUNT, TOPOLOGY } from '@/constants/simulation'

export interface Point {
  x: number
  y: number
}

export function getNodeCoords(id: number): Point {
  const angle = ((id - 1) * (360 / NODE_COUNT) * Math.PI) / 180
  return {
    x: Math.round(TOPOLOGY.centerX + TOPOLOGY.radius * Math.cos(angle)),
    y: Math.round(TOPOLOGY.centerY + TOPOLOGY.radius * Math.sin(angle)),
  }
}

export function pathFromNodeToCenter(id: number): string {
  const { x, y } = getNodeCoords(id)
  return `M ${x} ${y} L ${TOPOLOGY.centerX} ${TOPOLOGY.centerY}`
}

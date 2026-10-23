import { DEMO_SILO_GROUPS, groupNodes, useSiloStore } from '@/store/useSiloStore'
import { useSimulationStore } from '@/store/useSimulationStore'

const DEMO_LOCK_REASON = '실서버 데이터 조회 상태에서 그룹을 저장할 수 있습니다.'

/** 서버 그룹과 2단 집계 구조의 편집. 진행 중 라운드의 스냅샷은 유지된다. */
export function SiloGroups() {
  const demo = useSimulationStore((s) => s.mockEnabled)
  const { silos, groups: serverGroups, groupDraft: draft, editingGroupId, editGroup, patchGroup, saveGroup, deleteGroup, pending } = useSiloStore()
  const nodes = groupNodes(silos, demo)
  const groups = demo ? DEMO_SILO_GROUPS : serverGroups
  const nameOf = (id: string) => nodes.find((s) => s.serverId === id)?.name ?? id
  const locked = demo || pending
  return <section className="silo-group-panel" aria-label="서버 사일로 그룹">
    <div className="data-subhead"><i className="fa-solid fa-object-group" /> 사일로 그룹</div>
    <p className="desc">집계자를 지정하면 2단 그룹으로 저장합니다. 변경은 새 라운드부터 적용됩니다.</p>
    {groups.length === 0 ? <div className="deploy-empty">등록된 그룹이 없습니다. 아래에서 참여 사일로를 골라 그룹을 등록하세요.</div>
      : <div className="silo-group-grid">{groups.map((group) => <article key={group.group_id} className="silo-group-card">
        <div className="silo-group-card-head">
          <strong className="silo-group-name" title={group.group_id}>{group.group_id}</strong>
          <span className="model-badge">{group.aggregator_node_id ? `집계자 ${nameOf(group.aggregator_node_id)}` : '일반 그룹'}</span>
        </div>
        <div className="cleanse-counters">
          {group.member_node_ids.length === 0 ? <span className="cleanse-counter-empty">참여 사일로 없음</span>
            : group.member_node_ids.map((id) => <span key={id} className="cleanse-counter">{nameOf(id)}</span>)}
        </div>
        <div className="silo-group-actions">
          <button type="button" className="model-action" disabled={locked} title={demo ? DEMO_LOCK_REASON : undefined} onClick={() => editGroup(group)}>
            <i className="fa-solid fa-pen" /> 편집
          </button>
          <button type="button" className="model-action remove" disabled={locked} title={demo ? DEMO_LOCK_REASON : undefined} onClick={() => void deleteGroup(group.group_id)}>
            <i className="fa-solid fa-trash" /> 삭제
          </button>
        </div>
      </article>)}</div>}
    <form className="silo-group-form" onSubmit={(event) => { event.preventDefault(); void saveGroup(draft, editingGroupId !== null).then((saved) => { if (saved) editGroup(null) }) }}>
      <div className="model-form-grid">
        <div className="control-group"><label htmlFor="silo-group-id">그룹 식별자</label>
          <input id="silo-group-id" className="model-input" value={draft.group_id} required maxLength={64} disabled={editingGroupId !== null} onChange={(e) => patchGroup({ group_id: e.target.value })} /></div>
        <div className="control-group"><label htmlFor="silo-group-desc">설명</label>
          <input id="silo-group-desc" className="model-input" value={draft.description} onChange={(e) => patchGroup({ description: e.target.value })} /></div>
        <div className="control-group"><label htmlFor="silo-group-aggregator">집계자</label>
          <select id="silo-group-aggregator" className="model-input" value={draft.aggregator_node_id ?? ''} onChange={(e) => patchGroup({ aggregator_node_id: e.target.value || null, member_node_ids: draft.member_node_ids.filter((id) => id !== e.target.value) })}>
            <option value="">일반 그룹 (집계자 없음)</option>{nodes.map((s) => <option key={s.serverId} value={s.serverId}>{s.name}</option>)}
          </select></div>
      </div>
      <fieldset className="silo-group-fieldset" disabled={pending}><legend>참여 사일로</legend><div className="silo-group-members">{nodes.filter((s) => s.serverId !== draft.aggregator_node_id).map((s) => <label key={s.serverId} className="silo-group-member">
        <input type="checkbox" checked={draft.member_node_ids.includes(s.serverId)} onChange={(e) => patchGroup({ member_node_ids: e.target.checked ? [...draft.member_node_ids, s.serverId] : draft.member_node_ids.filter((id) => id !== s.serverId) })} /> {s.name}
      </label>)}</div></fieldset>
      <div className="silo-group-actions">
        <button type="submit" className="btn btn-primary" disabled={locked || !draft.group_id.trim() || draft.member_node_ids.length === 0}
          title={demo ? DEMO_LOCK_REASON : undefined}>{editingGroupId ? '그룹 변경 저장' : '그룹 등록'}</button>
        {editingGroupId && <button type="button" className="btn btn-secondary" onClick={() => editGroup(null)}>새 그룹 작성</button>}
      </div>
    </form>
  </section>
}

import { useSiloStore } from '@/store/useSiloStore'

/** 서버 그룹과 2단 집계 구조의 편집. 진행 중 라운드의 스냅샷은 유지된다. */
export function SiloGroups() {
  const { silos, groups, groupDraft: draft, editingGroupId, editGroup, patchGroup, saveGroup, deleteGroup, pending } = useSiloStore()
  const nodes = silos.filter((s) => s.serverId)
  return <section className="silo-group-panel" aria-label="서버 사일로 그룹">
    <h3>사일로 그룹</h3>
    <p className="silo-observation">집계자를 지정하면 2단 그룹으로 저장합니다. 변경은 새 라운드부터 적용됩니다.</p>
    <div className="silo-group-list">{groups.map((group) => <div key={group.group_id}>
      <strong>{group.group_id}</strong> · {group.aggregator_node_id ? `집계자 ${group.aggregator_node_id}` : '일반 그룹'} · {group.member_node_ids.join(', ')}
      <button type="button" className="model-action" disabled={pending} onClick={() => editGroup(group)}>편집</button>
      <button type="button" className="model-action remove" disabled={pending} onClick={() => void deleteGroup(group.group_id)}>삭제</button>
    </div>)}</div>
    <form onSubmit={(event) => { event.preventDefault(); void saveGroup(draft, editingGroupId !== null).then((saved) => { if (saved) editGroup(null) }) }}>
      <div className="model-form-grid">
        <label>그룹 식별자<input className="model-input" value={draft.group_id} required maxLength={64} disabled={editingGroupId !== null} onChange={(e) => patchGroup({ group_id: e.target.value })} /></label>
        <label>설명<input className="model-input" value={draft.description} onChange={(e) => patchGroup({ description: e.target.value })} /></label>
        <label>집계자<select className="model-input" value={draft.aggregator_node_id ?? ''} onChange={(e) => patchGroup({ aggregator_node_id: e.target.value || null, member_node_ids: draft.member_node_ids.filter((id) => id !== e.target.value) })}>
          <option value="">일반 그룹 (집계자 없음)</option>{nodes.map((s) => <option key={s.serverId} value={s.serverId}>{s.name} ({s.serverId})</option>)}
        </select></label>
      </div>
      <fieldset disabled={pending}><legend>참여 사일로</legend><div className="silo-group-members">{nodes.filter((s) => s.serverId !== draft.aggregator_node_id).map((s) => <label key={s.serverId}>
        <input type="checkbox" checked={draft.member_node_ids.includes(s.serverId!)} onChange={(e) => patchGroup({ member_node_ids: e.target.checked ? [...draft.member_node_ids, s.serverId!] : draft.member_node_ids.filter((id) => id !== s.serverId) })} /> {s.name} ({s.serverId})
      </label>)}</div></fieldset>
      <button type="submit" className="btn btn-primary" disabled={pending || !draft.group_id.trim() || draft.member_node_ids.length === 0}>{editingGroupId ? '그룹 변경 저장' : '그룹 등록'}</button>
      {editingGroupId && <button type="button" className="btn btn-secondary" onClick={() => editGroup(null)}>새 그룹 작성</button>}
    </form>
  </section>
}

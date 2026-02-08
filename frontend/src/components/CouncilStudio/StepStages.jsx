/**
 * StepStages - Stage configuration UI (Step 2)
 */

import { STAGE_KINDS, EXECUTION_MODES, MAX_STAGE_MEMBERS, MAX_STAGES } from './constants.js';

export default function StepStages({
    stages,
    members,
    selectedStageId,
    selectedStage,
    onSelectStage,
    onAddStage,
    onUpdateStage,
    onRemoveStage,
    onMoveStage,
    onToggleMember,
}) {
    return (
        <div className="studio-grid stage-layout">
            <div className="studio-panel stage-list">
                <div className="panel-header">
                    <h2>Stages</h2>
                    <button className="studio-btn" onClick={onAddStage} disabled={stages.length >= MAX_STAGES}>+ Add</button>
                </div>
                {stages.map((stage, idx) => (
                    <div key={stage.id} className={`stage-card ${selectedStageId === stage.id ? 'selected' : ''}`}>
                        <button className="stage-select" onClick={() => onSelectStage(stage.id)}>
                            <strong>{idx + 1}. {stage.name}</strong>
                            <small>{stage.kind} • {stage.execution_mode}</small>
                        </button>
                        {stage.kind !== 'synthesis' && (
                            <div className="stage-row-actions">
                                <button onClick={() => onMoveStage(stage.id, 'up')}>↑</button>
                                <button onClick={() => onMoveStage(stage.id, 'down')}>↓</button>
                                <button onClick={() => onRemoveStage(stage.id)}>Delete</button>
                            </div>
                        )}
                    </div>
                ))}
            </div>

            <div className="studio-panel">
                {selectedStage ? (
                    <>
                        <h2>Stage Configuration</h2>
                        <label>Name</label>
                        <input
                            value={selectedStage.name}
                            onChange={(e) => onUpdateStage(selectedStage.id, { name: e.target.value })}
                        />
                        <label>Kind</label>
                        <select
                            value={selectedStage.kind}
                            onChange={(e) => onUpdateStage(selectedStage.id, { kind: e.target.value })}
                            disabled={selectedStage.kind === 'synthesis'}
                        >
                            {STAGE_KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
                        </select>
                        <label>Execution</label>
                        <select
                            value={selectedStage.execution_mode}
                            onChange={(e) => onUpdateStage(selectedStage.id, { execution_mode: e.target.value })}
                            disabled={selectedStage.kind === 'synthesis'}
                        >
                            {EXECUTION_MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                        </select>
                        <label>Prompt</label>
                        <textarea
                            rows={8}
                            value={selectedStage.prompt}
                            onChange={(e) => onUpdateStage(selectedStage.id, { prompt: e.target.value })}
                        />
                        <label>{selectedStage.kind === 'synthesis' ? 'Chairman (exactly 1)' : `Members (max ${MAX_STAGE_MEMBERS})`}</label>
                        <div className="member-pills">
                            {members.map((member) => {
                                const active = selectedStage.member_ids.includes(member.id);
                                return (
                                    <button
                                        key={member.id}
                                        className={`pill ${active ? 'active' : ''}`}
                                        onClick={() => onToggleMember(selectedStage.id, member.id)}
                                    >
                                        {member.alias}
                                    </button>
                                );
                            })}
                        </div>
                    </>
                ) : (
                    <div className="empty">Select a stage to edit.</div>
                )}
            </div>
        </div>
    );
}

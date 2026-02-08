/**
 * StepRoles - Member management UI (Step 1)
 */

import { normalizeMaxOutputTokens } from '../../utils/councilStudioUtils.js';
import { DEFAULT_MEMBER_MAX_OUTPUT_TOKENS, MAX_MEMBER_MAX_OUTPUT_TOKENS } from './constants.js';

export default function StepRoles({
    members,
    models,
    selectedMemberId,
    selectedMember,
    onSelectMember,
    onAddMember,
    onUpdateMember,
    onRemoveMember,
}) {
    return (
        <div className="studio-grid two-col">
            <div className="studio-panel">
                <div className="panel-header">
                    <h2>Members</h2>
                    <button className="studio-btn" onClick={onAddMember}>
                        + Add
                    </button>
                </div>
                {members.map((member) => (
                    <button
                        key={member.id}
                        className={`list-row ${selectedMemberId === member.id ? 'selected' : ''}`}
                        onClick={() => onSelectMember(member.id)}
                    >
                        <div>{member.alias}</div>
                        <small>{member.model_id}</small>
                    </button>
                ))}
            </div>

            <div className="studio-panel">
                {selectedMember ? (
                    <>
                        <div className="panel-header">
                            <h2>Edit Member</h2>
                            <button
                                className="studio-btn danger"
                                onClick={() => onRemoveMember(selectedMember.id)}
                                disabled={members.length <= 1}
                            >
                                Delete
                            </button>
                        </div>
                        <label>Alias</label>
                        <input
                            value={selectedMember.alias}
                            onChange={(e) => onUpdateMember(selectedMember.id, { alias: e.target.value })}
                        />
                        <label>Model</label>
                        <select
                            value={selectedMember.model_id}
                            onChange={(e) => onUpdateMember(selectedMember.id, { model_id: e.target.value })}
                        >
                            {models.map((model) => (
                                <option key={model.id} value={model.id}>
                                    {model.label} ({model.id})
                                </option>
                            ))}
                        </select>
                        <label>System Prompt</label>
                        <textarea
                            rows={8}
                            value={selectedMember.system_prompt}
                            onChange={(e) => onUpdateMember(selectedMember.id, { system_prompt: e.target.value })}
                        />
                        <label>Max Output Tokens</label>
                        <input
                            type="number"
                            min={1}
                            max={MAX_MEMBER_MAX_OUTPUT_TOKENS}
                            value={selectedMember.max_output_tokens ?? DEFAULT_MEMBER_MAX_OUTPUT_TOKENS}
                            onChange={(e) =>
                                onUpdateMember(selectedMember.id, {
                                    max_output_tokens: normalizeMaxOutputTokens(e.target.value),
                                })
                            }
                        />
                    </>
                ) : (
                    <div className="empty">Select a member to edit.</div>
                )}
            </div>
        </div>
    );
}

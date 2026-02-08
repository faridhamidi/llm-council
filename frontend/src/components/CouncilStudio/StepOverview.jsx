/**
 * StepOverview - Validation and payload preview (Step 3)
 */

import { deriveChairmanId } from '../../utils/councilStudioUtils.js';

export default function StepOverview({ draft, validation }) {
    return (
        <div className="studio-grid two-col">
            <div className="studio-panel">
                <h2>Validation</h2>
                {validation.errors.length === 0 && validation.warnings.length === 0 && (
                    <div className="studio-status success">All checks passed.</div>
                )}
                {validation.errors.map((item, i) => (
                    <div key={`err-${i}`} className="studio-status error">{item}</div>
                ))}
                {validation.warnings.map((item, i) => (
                    <div key={`warn-${i}`} className="studio-status warn">{item}</div>
                ))}
            </div>
            <div className="studio-panel">
                <h2>Payload Preview</h2>
                <pre>{JSON.stringify({
                    members: draft.members,
                    chairman_id: deriveChairmanId(draft.stages, draft.chairman_id),
                    chairman_label: draft.chairman_label,
                    title_model_id: draft.title_model_id,
                    use_system_prompt_stage2: draft.use_system_prompt_stage2,
                    use_system_prompt_stage3: draft.use_system_prompt_stage3,
                    speaker_context_level: draft.speaker_context_level,
                    stages: draft.stages,
                }, null, 2)}</pre>
            </div>
        </div>
    );
}

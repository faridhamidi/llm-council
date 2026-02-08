/**
 * Validation and normalization logic for CouncilStudio
 */

import {
    randomId,
    normalizeMaxOutputTokens,
    inferStageKind,
    makeDefaultStages,
} from './councilStudioUtils.js';

const DEFAULT_MEMBER_MAX_OUTPUT_TOKENS = 10000;
const MAX_MEMBER_MAX_OUTPUT_TOKENS = 20000;
const MAX_STAGE_MEMBERS = 6;
const MAX_STAGES = 10;

/**
 * Normalize council settings with model validation and ID remapping
 * @param {Object} settings - Raw settings object
 * @param {Array} models - Available Bedrock models
 * @returns {Object} Normalized settings
 */
export const normalizeSettings = (settings, models) => {
    const modelIds = new Set((models || []).map((m) => m.id));
    const fallbackModel = models?.[0]?.id || '';
    const resolveModelId = (modelId) => {
        const candidate = (modelId || '').trim();
        if (!candidate) return modelIds.size > 0 ? fallbackModel : '';
        if (modelIds.size === 0) return candidate;
        return modelIds.has(candidate) ? candidate : (fallbackModel || candidate);
    };

    const memberIdMap = new Map();
    const nextMembers = [];
    const usedMemberIds = new Set();

    for (const member of settings.members || []) {
        const rawId = (member.id || '').trim() || randomId('member');
        const nextId = usedMemberIds.has(rawId) ? randomId('member') : rawId;
        usedMemberIds.add(nextId);
        memberIdMap.set(rawId, nextId);
        if (!memberIdMap.has(nextId)) memberIdMap.set(nextId, nextId);

        nextMembers.push({
            id: nextId,
            alias: member.alias || `Member ${nextMembers.length + 1}`,
            model_id: resolveModelId(member.model_id),
            system_prompt: member.system_prompt || '',
            max_output_tokens: normalizeMaxOutputTokens(
                member.max_output_tokens,
                DEFAULT_MEMBER_MAX_OUTPUT_TOKENS,
                MAX_MEMBER_MAX_OUTPUT_TOKENS
            ),
        });
    }

    const remapId = (oldId) => memberIdMap.get(oldId) || oldId;

    const sourceStages = Array.isArray(settings.stages) && settings.stages.length > 0
        ? settings.stages
        : makeDefaultStages(nextMembers, remapId(settings.chairman_id));

    const validMemberIds = new Set(nextMembers.map((m) => m.id));
    const usedStageIds = new Set();
    const normalizedStages = sourceStages.map((stage, index) => {
        const rawStageId = (stage.id || '').trim() || `stage-${index + 1}`;
        const stageId = usedStageIds.has(rawStageId) ? randomId('stage') : rawStageId;
        usedStageIds.add(stageId);

        const remapped = (stage.member_ids || [])
            .map((mid) => remapId(mid))
            .filter((mid) => validMemberIds.has(mid));
        const memberIds = [...new Set(remapped)];

        return {
            id: stageId,
            name: stage.name || `Stage ${index + 1}`,
            kind: inferStageKind(stage, index),
            prompt: stage.prompt || '',
            execution_mode: stage.execution_mode === 'sequential' ? 'sequential' : 'parallel',
            member_ids: memberIds,
        };
    });

    let synthesisIndex = normalizedStages.findIndex((s) => s.kind === 'synthesis');
    if (synthesisIndex === -1) {
        const fallbackChairman = nextMembers[0]?.id || '';
        normalizedStages.push({
            id: randomId('stage'),
            name: 'Final Synthesis',
            kind: 'synthesis',
            prompt: '',
            execution_mode: 'sequential',
            member_ids: fallbackChairman ? [fallbackChairman] : [],
        });
        synthesisIndex = normalizedStages.length - 1;
    }

    // Keep only one synthesis stage; convert extras to responses.
    normalizedStages.forEach((stage, index) => {
        if (stage.kind === 'synthesis' && index !== synthesisIndex) {
            stage.kind = 'responses';
        }
    });

    const synthesisStage = normalizedStages[synthesisIndex];
    synthesisStage.execution_mode = 'sequential';
    if (!synthesisStage.member_ids.length && nextMembers[0]) {
        synthesisStage.member_ids = [nextMembers[0].id];
    }
    if (synthesisStage.member_ids.length > 1) {
        synthesisStage.member_ids = [synthesisStage.member_ids[0]];
    }

    // Ensure synthesis stage is last.
    if (synthesisIndex !== normalizedStages.length - 1) {
        normalizedStages.splice(synthesisIndex, 1);
        normalizedStages.push(synthesisStage);
    }

    const chairmanId = synthesisStage.member_ids[0] || nextMembers[0]?.id || '';

    return {
        members: nextMembers,
        stages: normalizedStages,
        chairman_id: chairmanId,
        chairman_label: settings.chairman_label || 'Chairman',
        title_model_id: resolveModelId(settings.title_model_id),
        use_system_prompt_stage2: settings.use_system_prompt_stage2 ?? true,
        use_system_prompt_stage3: settings.use_system_prompt_stage3 ?? true,
        speaker_context_level: settings.speaker_context_level || 'full',
    };
};

/**
 * Validate draft configuration
 * @param {Object} draft - Draft settings to validate
 * @returns {Object} Validation result with errors and warnings arrays
 */
export const validateDraft = (draft) => {
    const errors = [];
    const warnings = [];

    const memberIds = draft.members.map((m) => m.id);
    if (new Set(memberIds).size !== memberIds.length) {
        errors.push('Member IDs must be unique.');
    }

    if (!draft.members.length) errors.push('At least one member is required.');
    if (!draft.title_model_id) errors.push('Title model is required.');
    for (const member of draft.members) {
        if (member.max_output_tokens < 1 || member.max_output_tokens > MAX_MEMBER_MAX_OUTPUT_TOKENS) {
            errors.push(`Member '${member.alias}' max output tokens must be between 1 and ${MAX_MEMBER_MAX_OUTPUT_TOKENS}.`);
            break;
        }
    }

    if (!draft.stages.length) errors.push('At least one stage is required.');
    if (draft.stages.length > MAX_STAGES) errors.push(`Maximum ${MAX_STAGES} stages allowed.`);

    let synthesisCount = 0;
    draft.stages.forEach((stage, index) => {
        if (!stage.name.trim()) errors.push(`Stage ${index + 1} name cannot be empty.`);
        if (!stage.member_ids.length) errors.push(`Stage '${stage.name || index + 1}' must include at least one member.`);
        if (stage.member_ids.length > MAX_STAGE_MEMBERS) {
            errors.push(`Stage '${stage.name || index + 1}' exceeds ${MAX_STAGE_MEMBERS} members.`);
        }

        if (stage.kind === 'rankings' && !stage.prompt.includes('{responses}')) {
            warnings.push(`Rankings stage '${stage.name || index + 1}' should include {responses}.`);
        }

        if (stage.kind === 'synthesis') {
            synthesisCount += 1;
            if (index !== draft.stages.length - 1) {
                errors.push('Synthesis stage must be the final stage.');
            }
            if (stage.member_ids.length !== 1) {
                errors.push('Synthesis stage must include exactly one member (chairman).');
            }
        }
    });

    if (synthesisCount === 0) {
        errors.push('A synthesis stage is required.');
    }
    if (synthesisCount > 1) {
        errors.push('Only one synthesis stage is allowed.');
    }

    return { errors, warnings };
};

/**
 * Utility functions for CouncilStudio
 * Pure functions with no React dependencies
 */

/**
 * Generate a random ID with a prefix
 * @param {string} prefix - Prefix for the ID
 * @returns {string} Random ID
 */
export const randomId = (prefix) => {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
        return `${prefix}-${crypto.randomUUID()}`;
    }
    return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
};

/**
 * Normalize max output tokens to valid range
 * @param {number|string} value - Token value to normalize
 * @returns {number} Normalized token count
 */
export const normalizeMaxOutputTokens = (value, defaultTokens = 10000, maxTokens = 20000) => {
    const parsed = Number.parseInt(`${value ?? ''}`, 10);
    if (!Number.isFinite(parsed) || parsed < 1) return defaultTokens;
    return Math.min(parsed, maxTokens);
};

/**
 * Infer stage kind based on stage configuration and position
 * @param {Object} stage - Stage object
 * @param {number} index - Stage index
 * @returns {string} Stage kind: 'responses', 'rankings', or 'synthesis'
 */
export const inferStageKind = (stage, index) => {
    if (['responses', 'rankings', 'synthesis'].includes(stage.kind)) return stage.kind;
    if (index === 1) return 'rankings';
    if (index === 2) return 'synthesis';
    return 'responses';
};

/**
 * Derive chairman ID from stages
 * @param {Array} stages - List of stages
 * @param {string} fallbackId - Fallback ID if no synthesis stage found
 * @returns {string} Chairman member ID
 */
export const deriveChairmanId = (stages, fallbackId) => {
    const synthesis = stages.find((s) => s.kind === 'synthesis');
    if (synthesis?.member_ids?.[0]) return synthesis.member_ids[0];
    const last = stages[stages.length - 1];
    if (last?.member_ids?.[0]) return last.member_ids[0];
    return fallbackId;
};

/**
 * Build fallback model options from existing settings
 * @param {Object} settings - Council settings
 * @returns {Array} Model options
 */
export const buildFallbackModelOptions = (settings) => {
    const ids = new Set();
    if (settings?.title_model_id) ids.add(settings.title_model_id);
    for (const member of settings?.members || []) {
        if (member?.model_id) ids.add(member.model_id);
    }
    return [...ids].map((id) => ({ id, label: id }));
};

/**
 * Create default stages configuration
 * @param {Array} members - List of members
 * @param {string} chairmanId - Chairman member ID
 * @returns {Array} Default stages
 */
export const makeDefaultStages = (members, chairmanId) => {
    const memberIds = members.map((m) => m.id);
    const finalChairman = memberIds.includes(chairmanId) ? chairmanId : (memberIds[0] || '');
    return [
        {
            id: 'stage-1',
            name: 'Individual Responses',
            kind: 'responses',
            prompt: '',
            execution_mode: 'parallel',
            member_ids: [...memberIds],
        },
        {
            id: 'stage-2',
            name: 'Peer Rankings',
            kind: 'rankings',
            prompt: '',
            execution_mode: 'parallel',
            member_ids: [...memberIds],
        },
        {
            id: 'stage-3',
            name: 'Final Synthesis',
            kind: 'synthesis',
            prompt: '',
            execution_mode: 'sequential',
            member_ids: finalChairman ? [finalChairman] : [],
        },
    ];
};

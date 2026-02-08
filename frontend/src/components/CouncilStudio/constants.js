/**
 * Constants for CouncilStudio
 */

export const MAX_STAGE_MEMBERS = 6;
export const MAX_STAGES = 10;
export const DEFAULT_MEMBER_MAX_OUTPUT_TOKENS = 10000;
export const MAX_MEMBER_MAX_OUTPUT_TOKENS = 20000;

export const STAGE_KINDS = [
    { value: 'responses', label: 'Responses' },
    { value: 'rankings', label: 'Rankings' },
    { value: 'synthesis', label: 'Synthesis' },
];

export const EXECUTION_MODES = [
    { value: 'parallel', label: 'Parallel' },
    { value: 'sequential', label: 'Sequential' },
];

export const STEP_ITEMS = [
    { id: 1, label: 'Roles' },
    { id: 2, label: 'Stages' },
    { id: 3, label: 'Overview' },
];

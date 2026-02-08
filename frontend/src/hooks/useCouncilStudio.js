/**
 * Custom hook for CouncilStudio state management
 * Encapsulates all state, side effects, and business logic
 */

import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import {
    randomId,
    deriveChairmanId,
    buildFallbackModelOptions,
} from '../utils/councilStudioUtils.js';
import {
    normalizeSettings,
    validateDraft,
} from '../utils/councilStudioValidation.js';

const DEFAULT_MEMBER_MAX_OUTPUT_TOKENS = 10000;
const MAX_STAGES = 10;
const MAX_STAGE_MEMBERS = 6;

export function useCouncilStudio() {
    // State
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const [warning, setWarning] = useState('');
    const [status, setStatus] = useState('');
    const [models, setModels] = useState([]);
    const [draft, setDraft] = useState(null);
    const [selectedMemberId, setSelectedMemberId] = useState('');
    const [selectedStageId, setSelectedStageId] = useState('');
    const [presets, setPresets] = useState([]);
    const [selectedPresetId, setSelectedPresetId] = useState('');
    const [presetNameInput, setPresetNameInput] = useState('');
    const [presetStatus, setPresetStatus] = useState(null);

    // Load initial data
    useEffect(() => {
        let mounted = true;
        const load = async () => {
            setLoading(true);
            setError('');
            setWarning('');
            try {
                const settings = await api.getCouncilSettings();
                if (!mounted) return;
                const [modelsResult, presetsResult] = await Promise.allSettled([
                    api.listBedrockModels(),
                    api.listCouncilPresets(),
                ]);
                if (!mounted) return;

                const listedModels = modelsResult.status === 'fulfilled'
                    ? (modelsResult.value?.models || [])
                    : [];
                const availableModels = listedModels.length > 0
                    ? listedModels
                    : buildFallbackModelOptions(settings);
                if (modelsResult.status === 'rejected') {
                    const reason = modelsResult.reason?.message || 'Failed to load Bedrock models.';
                    setWarning(`Loaded settings, but model list is unavailable: ${reason}`);
                }

                if (presetsResult.status === 'fulfilled') {
                    setPresets(presetsResult.value?.presets || []);
                } else {
                    setPresets([]);
                }

                setModels(availableModels);
                const normalized = normalizeSettings(settings, availableModels);
                setDraft(normalized);
                setSelectedMemberId(normalized.members[0]?.id || '');
                setSelectedStageId(normalized.stages[0]?.id || '');
            } catch (err) {
                setError(err.message || 'Failed to load council settings.');
            } finally {
                if (mounted) setLoading(false);
            }
        };
        load();
        return () => {
            mounted = false;
        };
    }, []);

    // Computed values
    const selectedMember = useMemo(
        () => draft?.members?.find((m) => m.id === selectedMemberId),
        [draft, selectedMemberId]
    );

    const selectedStage = useMemo(
        () => draft?.stages?.find((s) => s.id === selectedStageId),
        [draft, selectedStageId]
    );

    const validation = useMemo(() => (draft ? validateDraft(draft) : { errors: [], warnings: [] }), [draft]);

    // Member actions
    const updateMember = (memberId, updates) => {
        setDraft((prev) => {
            if (!prev) return prev;
            return {
                ...prev,
                members: prev.members.map((m) => (m.id === memberId ? { ...m, ...updates } : m)),
            };
        });
    };

    const addMember = () => {
        setDraft((prev) => {
            if (!prev) return prev;
            const usedIds = new Set(prev.members.map((m) => m.id));
            let id = randomId('member');
            while (usedIds.has(id)) id = randomId('member');
            const next = {
                id,
                alias: `Member ${prev.members.length + 1}`,
                model_id: models[0]?.id || prev.title_model_id || prev.members[0]?.model_id || '',
                system_prompt: '',
                max_output_tokens: DEFAULT_MEMBER_MAX_OUTPUT_TOKENS,
            };
            return { ...prev, members: [...prev.members, next] };
        });
    };

    const removeMember = (memberId) => {
        setDraft((prev) => {
            if (!prev || prev.members.length <= 1) return prev;
            const nextMembers = prev.members.filter((m) => m.id !== memberId);
            const nextStages = prev.stages.map((s) => {
                const nextMemberIds = s.member_ids.filter((id) => id !== memberId);
                if (s.kind === 'synthesis' && nextMemberIds.length === 0 && nextMembers[0]) {
                    return { ...s, member_ids: [nextMembers[0].id] };
                }
                return { ...s, member_ids: nextMemberIds };
            });
            return {
                ...prev,
                members: nextMembers,
                stages: nextStages,
            };
        });
        setSelectedMemberId((prev) => (prev === memberId ? '' : prev));
    };

    // Stage actions
    const addStage = () => {
        setDraft((prev) => {
            if (!prev || prev.stages.length >= MAX_STAGES) return prev;
            const synthesisIndex = prev.stages.findIndex((s) => s.kind === 'synthesis');
            const insertIndex = synthesisIndex === -1 ? prev.stages.length : synthesisIndex;
            const next = {
                id: randomId('stage'),
                name: `Stage ${insertIndex + 1}`,
                kind: 'responses',
                prompt: '',
                execution_mode: 'parallel',
                member_ids: prev.members[0] ? [prev.members[0].id] : [],
            };
            const stages = [...prev.stages];
            stages.splice(insertIndex, 0, next);
            return { ...prev, stages };
        });
    };

    const updateStage = (stageId, updates) => {
        setDraft((prev) => {
            if (!prev) return prev;
            let stages = prev.stages.map((s) => (s.id === stageId ? { ...s, ...updates } : s));

            stages = stages.map((s) => {
                if (s.kind === 'synthesis') {
                    const oneMember = s.member_ids?.length ? [s.member_ids[0]] : [];
                    return { ...s, execution_mode: 'sequential', member_ids: oneMember };
                }
                return s;
            });

            const synthesisIndex = stages.findIndex((s) => s.kind === 'synthesis');
            if (synthesisIndex !== -1 && synthesisIndex !== stages.length - 1) {
                const synthesisStage = stages[synthesisIndex];
                stages.splice(synthesisIndex, 1);
                stages.push(synthesisStage);
            }

            return {
                ...prev,
                stages,
                chairman_id: deriveChairmanId(stages, prev.chairman_id),
            };
        });
    };

    const removeStage = (stageId) => {
        setDraft((prev) => {
            if (!prev) return prev;
            const stage = prev.stages.find((s) => s.id === stageId);
            if (!stage || stage.kind === 'synthesis') return prev;
            const stages = prev.stages.filter((s) => s.id !== stageId);
            return {
                ...prev,
                stages,
                chairman_id: deriveChairmanId(stages, prev.chairman_id),
            };
        });
        setSelectedStageId((prev) => (prev === stageId ? '' : prev));
    };

    const moveStage = (stageId, direction) => {
        setDraft((prev) => {
            if (!prev) return prev;
            const index = prev.stages.findIndex((s) => s.id === stageId);
            if (index === -1) return prev;
            const stage = prev.stages[index];
            if (stage.kind === 'synthesis') return prev;
            const nextIndex = direction === 'up' ? index - 1 : index + 1;
            if (nextIndex < 0 || nextIndex >= prev.stages.length) return prev;
            if (prev.stages[nextIndex]?.kind === 'synthesis') return prev;
            const stages = [...prev.stages];
            [stages[index], stages[nextIndex]] = [stages[nextIndex], stages[index]];
            return { ...prev, stages };
        });
    };

    const toggleMemberInStage = (stageId, memberId) => {
        setDraft((prev) => {
            if (!prev) return prev;
            const stages = prev.stages.map((stage) => {
                if (stage.id !== stageId) return stage;
                if (stage.kind === 'synthesis') {
                    return { ...stage, member_ids: [memberId] };
                }
                const set = new Set(stage.member_ids);
                if (set.has(memberId)) {
                    set.delete(memberId);
                } else {
                    if (set.size >= MAX_STAGE_MEMBERS) return stage;
                    set.add(memberId);
                }
                return { ...stage, member_ids: [...set] };
            });
            return {
                ...prev,
                stages,
                chairman_id: deriveChairmanId(stages, prev.chairman_id),
            };
        });
    };

    // Settings actions
    const buildSettingsPayload = (settings) => ({
        members: settings.members,
        stages: settings.stages,
        chairman_id: deriveChairmanId(settings.stages, settings.chairman_id),
        chairman_label: settings.chairman_label || 'Chairman',
        title_model_id: settings.title_model_id,
        use_system_prompt_stage2: settings.use_system_prompt_stage2 ?? true,
        use_system_prompt_stage3: settings.use_system_prompt_stage3 ?? true,
        speaker_context_level: settings.speaker_context_level || 'full',
    });

    const handleSave = async () => {
        if (!draft) return;
        setStatus('');
        setError('');

        const normalized = normalizeSettings(draft, models);
        const validationResult = validateDraft(normalized);
        if (validationResult.errors.length) {
            setError(validationResult.errors[0]);
            return;
        }

        const payload = buildSettingsPayload(normalized);

        setSaving(true);
        try {
            const response = await api.updateCouncilSettings(payload);
            const serverSettings = response.settings || payload;
            const next = normalizeSettings(serverSettings, models);
            setDraft(next);
            setStatus('Council settings saved.');
        } catch (err) {
            setError(err.message || 'Failed to save council settings.');
        } finally {
            setSaving(false);
        }
    };

    // Preset actions
    const handleSavePreset = async () => {
        if (!draft) return;
        const trimmedName = presetNameInput.trim();
        if (!trimmedName) {
            setPresetStatus({ type: 'error', message: 'Preset name is required.' });
            return;
        }
        setPresetStatus(null);
        try {
            const normalized = normalizeSettings(draft, models);
            const response = await api.saveCouncilPreset(trimmedName, buildSettingsPayload(normalized));
            const nextPresets = response.presets || [];
            setPresets(nextPresets);
            setPresetNameInput('');
            const matched = nextPresets.find((preset) => preset.name === trimmedName);
            if (matched?.id) setSelectedPresetId(matched.id);
            setPresetStatus({
                type: 'success',
                message: response.updated ? 'Preset updated.' : 'Preset saved.',
            });
        } catch (err) {
            setPresetStatus({ type: 'error', message: err.message || 'Failed to save preset.' });
        }
    };

    const handleApplyPreset = async () => {
        if (!selectedPresetId) {
            setPresetStatus({ type: 'error', message: 'Select a preset to apply.' });
            return;
        }
        setPresetStatus(null);
        try {
            const response = await api.applyCouncilPreset(selectedPresetId);
            if (response.settings) {
                const next = normalizeSettings(response.settings, models);
                setDraft(next);
                setSelectedMemberId(next.members[0]?.id || '');
                setSelectedStageId(next.stages[0]?.id || '');
            }
            setPresetStatus({ type: 'success', message: 'Preset applied.' });
        } catch (err) {
            setPresetStatus({ type: 'error', message: err.message || 'Failed to apply preset.' });
        }
    };

    const handleDeletePreset = async () => {
        if (!selectedPresetId) {
            setPresetStatus({ type: 'error', message: 'Select a preset to delete.' });
            return;
        }
        setPresetStatus(null);
        try {
            const response = await api.deleteCouncilPreset(selectedPresetId);
            setPresets(response.presets || []);
            setSelectedPresetId('');
            setPresetStatus({ type: 'success', message: 'Preset deleted.' });
        } catch (err) {
            setPresetStatus({ type: 'error', message: err.message || 'Failed to delete preset.' });
        }
    };

    // Export action
    const handleExportStored = async () => {
        setStatus('');
        setError('');
        try {
            const stored = await api.getCouncilSettings();
            const blob = new Blob([JSON.stringify(stored, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'council-settings-stored.json';
            a.click();
            URL.revokeObjectURL(url);
            setStatus('Exported stored council settings JSON.');
        } catch (err) {
            setError(err.message || 'Failed to export stored settings.');
        }
    };

    return {
        // State
        loading,
        saving,
        error,
        warning,
        status,
        models,
        draft,
        selectedMemberId,
        selectedStageId,
        presets,
        selectedPresetId,
        presetNameInput,
        presetStatus,
        validation,
        selectedMember,
        selectedStage,

        // Actions
        setSelectedMemberId,
        setSelectedStageId,
        setSelectedPresetId,
        setPresetNameInput,
        updateMember,
        addMember,
        removeMember,
        addStage,
        updateStage,
        removeStage,
        moveStage,
        toggleMemberInStage,
        handleSave,
        handleSavePreset,
        handleApplyPreset,
        handleDeletePreset,
        handleExportStored,
    };
}

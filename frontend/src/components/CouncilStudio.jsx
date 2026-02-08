import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import './CouncilStudio.css';

const MAX_STAGE_MEMBERS = 6;
const MAX_STAGES = 10;

const STAGE_KINDS = [
  { value: 'responses', label: 'Responses' },
  { value: 'rankings', label: 'Rankings' },
  { value: 'synthesis', label: 'Synthesis' },
];

const EXECUTION_MODES = [
  { value: 'parallel', label: 'Parallel' },
  { value: 'sequential', label: 'Sequential' },
];

const STEP_ITEMS = [
  { id: 1, label: 'Roles' },
  { id: 2, label: 'Stages' },
  { id: 3, label: 'Overview' },
];

const randomId = (prefix) => {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
};

const inferStageKind = (stage, index) => {
  if (['responses', 'rankings', 'synthesis'].includes(stage.kind)) return stage.kind;
  if (index === 1) return 'rankings';
  if (index === 2) return 'synthesis';
  return 'responses';
};

const makeDefaultStages = (members, chairmanId) => {
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

const buildFallbackModelOptions = (settings) => {
  const ids = new Set();
  if (settings?.title_model_id) ids.add(settings.title_model_id);
  for (const member of settings?.members || []) {
    if (member?.model_id) ids.add(member.model_id);
  }
  return [...ids].map((id) => ({ id, label: id }));
};

const normalizeSettings = (settings, models) => {
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

const deriveChairmanId = (stages, fallbackId) => {
  const synthesis = stages.find((s) => s.kind === 'synthesis');
  if (synthesis?.member_ids?.[0]) return synthesis.member_ids[0];
  const last = stages[stages.length - 1];
  if (last?.member_ids?.[0]) return last.member_ids[0];
  return fallbackId;
};

const validateDraft = (draft) => {
  const errors = [];
  const warnings = [];

  const memberIds = draft.members.map((m) => m.id);
  if (new Set(memberIds).size !== memberIds.length) {
    errors.push('Member IDs must be unique.');
  }

  if (!draft.members.length) errors.push('At least one member is required.');
  if (!draft.title_model_id) errors.push('Title model is required.');

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

export default function CouncilStudio({ onClose }) {
  const [step, setStep] = useState(1);
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

  const selectedMember = useMemo(
    () => draft?.members?.find((m) => m.id === selectedMemberId),
    [draft, selectedMemberId]
  );

  const selectedStage = useMemo(
    () => draft?.stages?.find((s) => s.id === selectedStageId),
    [draft, selectedStageId]
  );

  const validation = useMemo(() => (draft ? validateDraft(draft) : { errors: [], warnings: [] }), [draft]);

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

    const payload = {
      members: normalized.members,
      stages: normalized.stages,
      chairman_id: deriveChairmanId(normalized.stages, normalized.chairman_id),
      chairman_label: normalized.chairman_label || 'Chairman',
      title_model_id: normalized.title_model_id,
      use_system_prompt_stage2: normalized.use_system_prompt_stage2 ?? true,
      use_system_prompt_stage3: normalized.use_system_prompt_stage3 ?? true,
    };

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

  const buildSettingsPayload = (settings) => ({
    members: settings.members,
    stages: settings.stages,
    chairman_id: deriveChairmanId(settings.stages, settings.chairman_id),
    chairman_label: settings.chairman_label || 'Chairman',
    title_model_id: settings.title_model_id,
    use_system_prompt_stage2: settings.use_system_prompt_stage2 ?? true,
    use_system_prompt_stage3: settings.use_system_prompt_stage3 ?? true,
  });

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

  if (loading) {
    return (
      <div className="studio-page">
        <div className="studio-loading">Loading council studio...</div>
      </div>
    );
  }

  if (!draft) {
    return (
      <div className="studio-page">
        <div className="studio-error">{error || 'Failed to load studio.'}</div>
      </div>
    );
  }

  return (
    <div className="studio-page">
      <div className="studio-shell">
        <div className="studio-header">
          <div>
            <h1>Council Studio</h1>
            <p>Configure your LLM Council pipeline with roles, stages, and execution flow.</p>
          </div>
          <div className="studio-actions">
            <button className="studio-btn" onClick={handleExportStored}>Export Stored JSON</button>
            <button className="studio-btn primary" onClick={handleSave} disabled={saving}>
              {saving ? 'Saving...' : 'Save Settings'}
            </button>
            <button className="studio-btn" onClick={onClose}>Close</button>
          </div>
        </div>

        <div className="studio-stepper">
          {STEP_ITEMS.map((item, index) => (
            <div key={item.id} className="step-wrap">
              <button
                className={`step-node ${step === item.id ? 'active' : ''} ${step > item.id ? 'completed' : ''}`}
                onClick={() => setStep(item.id)}
              >
                <div className="step-number">{item.id}</div>
                <div className="step-label">{item.label}</div>
              </button>
              {index < STEP_ITEMS.length - 1 && <div className="step-divider" />}
            </div>
          ))}
        </div>

        {status && <div className="studio-status success">{status}</div>}
        {warning && <div className="studio-status warn">{warning}</div>}
        {error && <div className="studio-status error">{error}</div>}
        {presetStatus && (
          <div className={`studio-status ${presetStatus.type}`}>{presetStatus.message}</div>
        )}

        <div className="studio-presets">
          <div className="preset-row">
            <label htmlFor="council-preset-name">Save Preset</label>
            <div className="preset-controls">
              <input
                id="council-preset-name"
                type="text"
                placeholder="Enter preset name"
                value={presetNameInput}
                onChange={(e) => setPresetNameInput(e.target.value)}
              />
              <button className="studio-btn" onClick={handleSavePreset}>Save</button>
            </div>
          </div>
          <div className="preset-row">
            <label htmlFor="council-preset-select">Apply Preset</label>
            <div className="preset-controls">
              <select
                id="council-preset-select"
                value={selectedPresetId}
                onChange={(e) => setSelectedPresetId(e.target.value)}
              >
                <option value="">Select preset</option>
                {presets.map((preset) => (
                  <option key={preset.id} value={preset.id}>{preset.name}</option>
                ))}
              </select>
              <button className="studio-btn" onClick={handleApplyPreset}>Apply</button>
              <button className="studio-btn danger" onClick={handleDeletePreset}>Delete</button>
            </div>
          </div>
        </div>

        {step === 1 && (
          <div className="studio-grid two-col">
            <div className="studio-panel">
              <div className="panel-header">
                <h2>Members</h2>
                <button className="studio-btn" onClick={addMember}>+ Add</button>
              </div>
              {draft.members.map((member) => (
                <button
                  key={member.id}
                  className={`list-row ${selectedMemberId === member.id ? 'selected' : ''}`}
                  onClick={() => setSelectedMemberId(member.id)}
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
                      onClick={() => removeMember(selectedMember.id)}
                      disabled={draft.members.length <= 1}
                    >
                      Delete
                    </button>
                  </div>
                  <label>Alias</label>
                  <input
                    value={selectedMember.alias}
                    onChange={(e) => updateMember(selectedMember.id, { alias: e.target.value })}
                  />
                  <label>Model</label>
                  <select
                    value={selectedMember.model_id}
                    onChange={(e) => updateMember(selectedMember.id, { model_id: e.target.value })}
                  >
                    {models.map((model) => (
                      <option key={model.id} value={model.id}>{model.label} ({model.id})</option>
                    ))}
                  </select>
                  <label>System Prompt</label>
                  <textarea
                    rows={8}
                    value={selectedMember.system_prompt}
                    onChange={(e) => updateMember(selectedMember.id, { system_prompt: e.target.value })}
                  />
                </>
              ) : (
                <div className="empty">Select a member to edit.</div>
              )}
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="studio-grid stage-layout">
            <div className="studio-panel stage-list">
              <div className="panel-header">
                <h2>Stages</h2>
                <button className="studio-btn" onClick={addStage} disabled={draft.stages.length >= MAX_STAGES}>+ Add</button>
              </div>
              {draft.stages.map((stage, idx) => (
                <div key={stage.id} className={`stage-card ${selectedStageId === stage.id ? 'selected' : ''}`}>
                  <button className="stage-select" onClick={() => setSelectedStageId(stage.id)}>
                    <strong>{idx + 1}. {stage.name}</strong>
                    <small>{stage.kind} • {stage.execution_mode}</small>
                  </button>
                  {stage.kind !== 'synthesis' && (
                    <div className="stage-row-actions">
                      <button onClick={() => moveStage(stage.id, 'up')}>↑</button>
                      <button onClick={() => moveStage(stage.id, 'down')}>↓</button>
                      <button onClick={() => removeStage(stage.id)}>Delete</button>
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
                    onChange={(e) => updateStage(selectedStage.id, { name: e.target.value })}
                  />
                  <label>Kind</label>
                  <select
                    value={selectedStage.kind}
                    onChange={(e) => updateStage(selectedStage.id, { kind: e.target.value })}
                    disabled={selectedStage.kind === 'synthesis'}
                  >
                    {STAGE_KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
                  </select>
                  <label>Execution</label>
                  <select
                    value={selectedStage.execution_mode}
                    onChange={(e) => updateStage(selectedStage.id, { execution_mode: e.target.value })}
                    disabled={selectedStage.kind === 'synthesis'}
                  >
                    {EXECUTION_MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                  </select>
                  <label>Prompt</label>
                  <textarea
                    rows={8}
                    value={selectedStage.prompt}
                    onChange={(e) => updateStage(selectedStage.id, { prompt: e.target.value })}
                  />
                  <label>{selectedStage.kind === 'synthesis' ? 'Chairman (exactly 1)' : `Members (max ${MAX_STAGE_MEMBERS})`}</label>
                  <div className="member-pills">
                    {draft.members.map((member) => {
                      const active = selectedStage.member_ids.includes(member.id);
                      return (
                        <button
                          key={member.id}
                          className={`pill ${active ? 'active' : ''}`}
                          onClick={() => toggleMemberInStage(selectedStage.id, member.id)}
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
        )}

        {step === 3 && (
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
                stages: draft.stages,
              }, null, 2)}</pre>
            </div>
          </div>
        )}

        <div className="studio-footer-nav">
          <button className="studio-btn" onClick={() => setStep((prev) => Math.max(1, prev - 1))} disabled={step === 1}>Back</button>
          <button className="studio-btn" onClick={() => setStep((prev) => Math.min(3, prev + 1))} disabled={step === 3}>Next</button>
        </div>
      </div>
    </div>
  );
}

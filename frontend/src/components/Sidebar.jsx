import { useState, useEffect } from 'react';
import { api } from '../api';
import logoMark from '../assets/NetZero2050-logo.svg';
import './Sidebar.css';

export default function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  onDeleteConversation,
  accessKeyReady = true,
}) {
  const [isTokenModalOpen, setIsTokenModalOpen] = useState(false);
  const [tokenInput, setTokenInput] = useState('');
  const [tokenStatus, setTokenStatus] = useState(null);
  const [regionOptions, setRegionOptions] = useState([]);
  const [selectedRegion, setSelectedRegion] = useState('');
  const [regionStatus, setRegionStatus] = useState(null);
  const [isCouncilModalOpen, setIsCouncilModalOpen] = useState(false);
  const [councilSettings, setCouncilSettings] = useState(null);
  const [councilModels, setCouncilModels] = useState([]);
  const [councilError, setCouncilError] = useState(null);
  const [isCouncilSaving, setIsCouncilSaving] = useState(false);
  const [draggedIndex, setDraggedIndex] = useState(null);
  const [draggedStageIndex, setDraggedStageIndex] = useState(null);
  const [draggedMember, setDraggedMember] = useState(null);
  const [councilPresets, setCouncilPresets] = useState([]);
  const [selectedPresetId, setSelectedPresetId] = useState('');
  const [presetNameInput, setPresetNameInput] = useState('');
  const [presetStatus, setPresetStatus] = useState(null);

  const buildDefaultStages = (members, chairmanId) => {
    const memberIds = members.map((member) => member.id);
    const defaultChairman = memberIds.includes(chairmanId) ? chairmanId : memberIds[0] || '';
    return [
      {
        id: 'stage-1',
        name: 'Individual Responses',
        prompt: '',
        execution_mode: 'parallel',
        member_ids: memberIds,
      },
      {
        id: 'stage-2',
        name: 'Peer Rankings',
        prompt: '',
        execution_mode: 'parallel',
        member_ids: memberIds,
      },
      {
        id: 'stage-3',
        name: 'Final Synthesis',
        prompt: '',
        execution_mode: 'sequential',
        member_ids: defaultChairman ? [defaultChairman] : [],
      },
    ];
  };

  const normalizeStage = (stage, members, index, fallbackChairmanId) => {
    const memberIds = new Set(members.map((member) => member.id));
    const normalizedIds = (stage.member_ids || []).filter((id) => memberIds.has(id));
    const fallbackId = fallbackChairmanId || members[0]?.id;
    const ensuredIds = normalizedIds.length > 0 ? normalizedIds : (fallbackId ? [fallbackId] : []);
    return {
      id: stage.id || `stage-${index + 1}`,
      name: stage.name || `Stage ${index + 1}`,
      prompt: stage.prompt ?? '',
      execution_mode: stage.execution_mode === 'sequential' ? 'sequential' : 'parallel',
      member_ids: ensuredIds,
    };
  };

  const coerceCouncilSettings = (settings, models) => {
    if (!settings || !Array.isArray(models) || models.length === 0) return settings;
    const allowedIds = new Set(models.map((model) => model.id));
    const fallbackId = models[0].id;
    const nextMembers = (settings.members || []).map((member) => {
      const nextModelId = allowedIds.has(member.model_id) ? member.model_id : fallbackId;
      if (nextModelId === member.model_id) return member;
      return { ...member, model_id: nextModelId };
    });
    const memberIds = new Set(nextMembers.map((member) => member.id));
    const nextChairmanId = memberIds.has(settings.chairman_id)
      ? settings.chairman_id
      : nextMembers[0]?.id || settings.chairman_id;
    const nextTitleModelId = allowedIds.has(settings.title_model_id)
      ? settings.title_model_id
      : fallbackId;
    const stageSource = Array.isArray(settings.stages) && settings.stages.length > 0
      ? settings.stages
      : buildDefaultStages(nextMembers, nextChairmanId);
    const normalizedStages = stageSource.map((stage, index) =>
      normalizeStage(stage, nextMembers, index, nextChairmanId)
    );
    return {
      ...settings,
      members: nextMembers,
      chairman_id: nextChairmanId,
      title_model_id: nextTitleModelId,
      use_system_prompt_stage2: settings.use_system_prompt_stage2 ?? true,
      use_system_prompt_stage3: settings.use_system_prompt_stage3 ?? true,
      stages: normalizedStages,
    };
  };

  useEffect(() => {
    if (!accessKeyReady) return;
    let isMounted = true;
    const loadRegions = async () => {
      try {
        const [optionsResponse, regionResponse] = await Promise.all([
          api.listBedrockRegions(),
          api.getBedrockRegion(),
        ]);
        if (!isMounted) return;
        setRegionOptions(optionsResponse.regions || []);
        setSelectedRegion(regionResponse.region || '');
      } catch (error) {
        console.error('Failed to load region settings:', error);
      }
    };
    loadRegions();
    return () => {
      isMounted = false;
    };
  }, [accessKeyReady]);

  useEffect(() => {
    const isAnyModalOpen = isTokenModalOpen || isCouncilModalOpen;
    if (!isAnyModalOpen) return;

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        if (isCouncilModalOpen) {
          closeCouncilModal();
        } else {
          closeTokenModal();
        }
      }
    };

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isTokenModalOpen, isCouncilModalOpen]);

  const openTokenModal = () => {
    setTokenStatus(null);
    setTokenInput('');
    setIsTokenModalOpen(true);
  };

  const closeTokenModal = () => {
    setIsTokenModalOpen(false);
  };

  const handleTokenSubmit = async (event) => {
    event.preventDefault();
    const trimmed = tokenInput.trim();
    if (!trimmed) {
      setTokenStatus({ type: 'error', message: 'Token cannot be empty.' });
      return;
    }

    try {
      await api.updateBedrockToken(trimmed);
      setTokenStatus({ type: 'success', message: 'Token updated for this session.' });
      setIsTokenModalOpen(false);
    } catch (error) {
      setTokenStatus({ type: 'error', message: error.message || 'Failed to update token.' });
    }
  };

  const openCouncilModal = async () => {
    setCouncilError(null);
    setPresetStatus(null);
    setIsCouncilModalOpen(true);
    try {
      const [settingsResponse, modelsResponse, presetsResponse] = await Promise.all([
        api.getCouncilSettings(),
        api.listBedrockModels(),
        api.listCouncilPresets(),
      ]);
      const models = modelsResponse.models || [];
      setCouncilModels(models);
      setCouncilSettings(coerceCouncilSettings(settingsResponse, models));
      setCouncilPresets(presetsResponse.presets || []);
    } catch (error) {
      setCouncilError(error.message || 'Failed to load council settings.');
    }
  };

  const closeCouncilModal = () => {
    setIsCouncilModalOpen(false);
    setDraggedIndex(null);
    setDraggedStageIndex(null);
    setDraggedMember(null);
    setPresetNameInput('');
    setPresetStatus(null);
  };

  const updateMember = (memberId, updates) => {
    setCouncilSettings((prev) => {
      if (!prev) return prev;
      const nextMembers = prev.members.map((member) =>
        member.id === memberId ? { ...member, ...updates } : member
      );
      return { ...prev, members: nextMembers };
    });
  };

  const handleAddMember = () => {
    setCouncilSettings((prev) => {
      if (!prev) return prev;
      const maxMembers = prev.max_members || 7;
      if (prev.members.length >= maxMembers) return prev;
      const newId = typeof crypto !== 'undefined' && crypto.randomUUID
        ? crypto.randomUUID()
        : `member-${Date.now()}`;
      const defaultModel = councilModels[0]?.id || '';
      const newMember = {
        id: newId,
        alias: `Member ${prev.members.length + 1}`,
        model_id: defaultModel,
        system_prompt: '',
      };
      return { ...prev, members: [...prev.members, newMember] };
    });
  };

  const handleRemoveMember = (memberId) => {
    setCouncilSettings((prev) => {
      if (!prev) return prev;
      if (prev.members.length <= 1) return prev;
      const nextMembers = prev.members.filter((member) => member.id !== memberId);
      const nextChairman =
        prev.chairman_id === memberId && nextMembers.length
          ? nextMembers[0].id
          : prev.chairman_id;
      return { ...prev, members: nextMembers, chairman_id: nextChairman };
    });
  };

  const handleDragStart = (index) => {
    setDraggedIndex(index);
  };

  const handleDrop = (index) => {
    setCouncilSettings((prev) => {
      if (!prev || draggedIndex === null || draggedIndex === index) return prev;
      const nextMembers = [...prev.members];
      const [moved] = nextMembers.splice(draggedIndex, 1);
      nextMembers.splice(index, 0, moved);
      return { ...prev, members: nextMembers };
    });
    setDraggedIndex(null);
  };

  const updateStage = (stageId, updates) => {
    setCouncilSettings((prev) => {
      if (!prev) return prev;
      const nextStages = (prev.stages || []).map((stage) =>
        stage.id === stageId ? { ...stage, ...updates } : stage
      );
      return { ...prev, stages: nextStages };
    });
  };

  const handleStageDragStart = (index) => {
    setDraggedStageIndex(index);
  };

  const handleStageDrop = (index) => {
    setCouncilSettings((prev) => {
      if (!prev || draggedStageIndex === null || draggedStageIndex === index) return prev;
      const nextStages = [...(prev.stages || [])];
      const [moved] = nextStages.splice(draggedStageIndex, 1);
      nextStages.splice(index, 0, moved);
      return { ...prev, stages: nextStages };
    });
    setDraggedStageIndex(null);
  };

  const handleMemberDragStart = (memberId, stageId) => {
    setDraggedMember({ memberId, stageId });
  };

  const handleMemberDrop = (targetStageId) => {
    setCouncilSettings((prev) => {
      if (!prev || !draggedMember) return prev;
      if (draggedMember.stageId === targetStageId) return prev;
      const nextStages = (prev.stages || []).map((stage) => {
        if (stage.id === draggedMember.stageId) {
          return {
            ...stage,
            member_ids: stage.member_ids.filter((id) => id !== draggedMember.memberId),
          };
        }
        if (stage.id === targetStageId) {
          if (stage.member_ids.length >= 5) {
            return stage;
          }
          if (stage.member_ids.includes(draggedMember.memberId)) {
            return stage;
          }
          return {
            ...stage,
            member_ids: [...stage.member_ids, draggedMember.memberId],
          };
        }
        return stage;
      });
      return { ...prev, stages: nextStages };
    });
    setDraggedMember(null);
  };

  const handleAddStage = () => {
    setCouncilSettings((prev) => {
      if (!prev) return prev;
      const stages = prev.stages || [];
      if (stages.length >= 10) return prev;
      const newId = typeof crypto !== 'undefined' && crypto.randomUUID
        ? crypto.randomUUID()
        : `stage-${Date.now()}`;
      const fallbackMember = prev.chairman_id || prev.members[0]?.id;
      const nextStage = {
        id: newId,
        name: `Stage ${stages.length + 1}`,
        prompt: '',
        execution_mode: 'parallel',
        member_ids: fallbackMember ? [fallbackMember] : [],
      };
      return { ...prev, stages: [...stages, nextStage] };
    });
  };

  const handleRemoveStage = (stageId) => {
    setCouncilSettings((prev) => {
      if (!prev) return prev;
      const nextStages = (prev.stages || []).filter((stage) => stage.id !== stageId);
      if (nextStages.length === 0) return prev;
      return { ...prev, stages: nextStages };
    });
  };

  const handleSaveCouncil = async () => {
    if (!councilSettings) return;
    setIsCouncilSaving(true);
    setCouncilError(null);
    try {
      const nextSettings = coerceCouncilSettings(councilSettings, councilModels);
      if (nextSettings !== councilSettings) {
        setCouncilSettings(nextSettings);
      }
      const payload = {
        members: nextSettings.members,
        chairman_id: nextSettings.chairman_id,
        chairman_label: nextSettings.chairman_label || 'Chairman',
        title_model_id: nextSettings.title_model_id,
        use_system_prompt_stage2: nextSettings.use_system_prompt_stage2 ?? true,
        use_system_prompt_stage3: nextSettings.use_system_prompt_stage3 ?? true,
        stages: nextSettings.stages || [],
      };
      await api.updateCouncilSettings(payload);
      setCouncilSettings((prev) => (prev ? { ...prev, ...payload } : prev));
      setIsCouncilModalOpen(false);
    } catch (error) {
      setCouncilError(error.message || 'Failed to update council settings.');
    } finally {
      setIsCouncilSaving(false);
    }
  };

  const handleRegionUpdate = async () => {
    if (!selectedRegion) {
      setRegionStatus({ type: 'error', message: 'Select a region first.' });
      return;
    }
    try {
      const response = await api.updateBedrockRegion(selectedRegion);
      setRegionStatus({ type: 'success', message: `Region set to ${selectedRegion}` });
      if (response.settings && isCouncilModalOpen) {
        const modelsResponse = await api.listBedrockModels();
        const models = modelsResponse.models || [];
        setCouncilModels(models);
        setCouncilSettings(coerceCouncilSettings(response.settings, models));
      }
    } catch (error) {
      setRegionStatus({ type: 'error', message: error.message || 'Failed to update region.' });
    }
  };

  const handleSavePreset = async () => {
    if (!councilSettings) return;
    const trimmedName = presetNameInput.trim();
    if (!trimmedName) {
      setPresetStatus({ type: 'error', message: 'Preset name is required.' });
      return;
    }
    setPresetStatus(null);
    try {
      const nextSettings = coerceCouncilSettings(councilSettings, councilModels);
      const response = await api.saveCouncilPreset(trimmedName, {
        members: nextSettings.members,
        chairman_id: nextSettings.chairman_id,
        chairman_label: nextSettings.chairman_label || 'Chairman',
        title_model_id: nextSettings.title_model_id,
        stages: nextSettings.stages || [],
      });
      setCouncilPresets(response.presets || []);
      setPresetNameInput('');
      setPresetStatus({
        type: 'success',
        message: response.updated ? 'Preset updated.' : 'Preset saved.',
      });
    } catch (error) {
      setPresetStatus({ type: 'error', message: error.message || 'Failed to save preset.' });
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
        setCouncilSettings(coerceCouncilSettings(response.settings, councilModels));
      }
      setPresetStatus({ type: 'success', message: 'Preset applied.' });
    } catch (error) {
      setPresetStatus({ type: 'error', message: error.message || 'Failed to apply preset.' });
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
      setCouncilPresets(response.presets || []);
      setSelectedPresetId('');
      setPresetStatus({ type: 'success', message: 'Preset deleted.' });
    } catch (error) {
      setPresetStatus({ type: 'error', message: error.message || 'Failed to delete preset.' });
    }
  };

  return (
    <div className="sidebar">
      <div className="logo-section">
        <div className="logo-row">
          <div className="logo-icon" aria-hidden="true">
            <img src={logoMark} alt="" className="logo-mark" />
          </div>
          <div className="logo-text">
            <div className="logo-title">LLM Council</div>
            <div className="subtitle">Collaborative AI</div>
          </div>
        </div>
      </div>

      <div className="sidebar-actions">
        <button className="action-btn primary" onClick={onNewConversation}>
          <span>+ New Conversation</span>
        </button>
        <button className="action-btn" onClick={openTokenModal}>
          <span>Refresh Bedrock Token</span>
        </button>
        <button className="action-btn" onClick={openCouncilModal}>
          <span>Council Settings</span>
        </button>
      </div>

      <div className="bedrock-section">
        <label htmlFor="bedrock-region-select">Bedrock Region</label>
        <select
          id="bedrock-region-select"
          value={selectedRegion}
          onChange={(event) => setSelectedRegion(event.target.value)}
        >
          <option value="">Select region</option>
          {regionOptions.map((region) => (
            <option key={region.code} value={region.code}>
              {region.label} ({region.code})
            </option>
          ))}
        </select>
        <button className="action-btn bedrock-update" onClick={handleRegionUpdate}>
          <span>Update</span>
        </button>
        {regionStatus && (
          <div className={`token-status ${regionStatus.type}`}>
            {regionStatus.message}
          </div>
        )}
        {tokenStatus && (
          <div className={`token-status ${tokenStatus.type}`}>
            {tokenStatus.message}
          </div>
        )}
      </div>

      <div className="conversations-header">Recent Sessions</div>

      <div className="conversation-list">
        {conversations.length === 0 ? (
          <div className="no-conversations">No conversations yet</div>
        ) : (
          conversations.map((conv) => (
            <div
              key={conv.id}
              className={`conversation-item ${
                conv.id === currentConversationId ? 'active' : ''
              }`}
              onClick={() => onSelectConversation(conv.id)}
            >
              <div className="conversation-row">
                <div className="conversation-title">
                  {conv.title || 'New Conversation'}
                </div>
                <button
                  className="conversation-delete-btn"
                  onClick={(event) => {
                    event.stopPropagation();
                    onDeleteConversation(conv.id);
                  }}
                  aria-label="Delete conversation"
                  title="Delete conversation"
                >
                  ×
                </button>
              </div>
              <div className="conversation-meta">
                {conv.message_count} messages
              </div>
            </div>
          ))
        )}
      </div>

      {isTokenModalOpen && (
        <div className="token-modal-backdrop" onClick={closeTokenModal}>
          <div className="token-modal" onClick={(event) => event.stopPropagation()}>
            <div className="token-modal-header">
              <h3>Update Bedrock API Key</h3>
              <button className="token-modal-close" onClick={closeTokenModal}>
                ×
              </button>
            </div>
            <form className="token-modal-body" onSubmit={handleTokenSubmit}>
              <label htmlFor="bedrock-token-input">Paste new token</label>
              <textarea
                id="bedrock-token-input"
                value={tokenInput}
                onChange={(event) => setTokenInput(event.target.value)}
                placeholder="bedrock-api-key-..."
                rows={4}
              />
              {tokenStatus && tokenStatus.type === 'error' && (
                <div className="token-status error">{tokenStatus.message}</div>
              )}
              <div className="token-modal-actions">
                <button type="button" className="token-cancel-btn" onClick={closeTokenModal}>
                  Cancel
                </button>
                <button type="submit" className="token-save-btn">
                  Update Token
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {isCouncilModalOpen && (
        <div className="token-modal-backdrop" onClick={closeCouncilModal}>
          <div className="token-modal council-modal" onClick={(event) => event.stopPropagation()}>
            <div className="token-modal-header modal-header">
              <div>
                <div className="modal-title">Council Members</div>
                {councilSettings && (
                  <div className="modal-meta">
                    {councilSettings.members.length} / {councilSettings.max_members || 7} members configured
                  </div>
                )}
              </div>
              <button className="token-modal-close close-btn" onClick={closeCouncilModal}>
                ×
              </button>
            </div>
            <div className="council-modal-body">
              {councilSettings && (
                <div className="modal-controls">
                  <div className="control-row">
                    <span className="control-label">Title Model</span>
                    <select
                      className="control-input"
                      value={councilSettings.title_model_id}
                      onChange={(event) =>
                        setCouncilSettings((prev) => ({ ...prev, title_model_id: event.target.value }))
                      }
                    >
                      {councilModels.map((model) => (
                        <option key={model.id} value={model.id}>
                          {model.label} ({model.id})
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="checkbox-container">
                    <label className="checkbox-label">
                      <input
                        type="checkbox"
                        checked={
                          !(councilSettings.use_system_prompt_stage2 ?? true) &&
                          !(councilSettings.use_system_prompt_stage3 ?? true)
                        }
                        onChange={(event) =>
                          setCouncilSettings((prev) => ({
                            ...prev,
                            use_system_prompt_stage2: !event.target.checked,
                            use_system_prompt_stage3: !event.target.checked,
                          }))
                        }
                      />
                      Disable system prompts in Stage 2 & 3
                    </label>
                  </div>
                  <div className="control-row">
                    <span className="control-label">Save Preset</span>
                    <input
                      className="control-input"
                      type="text"
                      placeholder="Enter preset name"
                      value={presetNameInput}
                      onChange={(event) => setPresetNameInput(event.target.value)}
                    />
                    <button className="small-btn" onClick={handleSavePreset}>
                      Save
                    </button>
                  </div>
                  <div className="control-row">
                    <span className="control-label">Apply Preset</span>
                    <select
                      className="control-input"
                      value={selectedPresetId}
                      onChange={(event) => setSelectedPresetId(event.target.value)}
                    >
                      <option value="">Select preset</option>
                      {councilPresets.map((preset) => (
                        <option key={preset.id} value={preset.id}>
                          {preset.name}
                        </option>
                      ))}
                    </select>
                    <div className="button-group">
                      <button className="small-btn" onClick={handleApplyPreset}>
                        Apply
                      </button>
                      <button className="small-btn delete" onClick={handleDeletePreset}>
                        Delete
                      </button>
                    </div>
                  </div>
                </div>
              )}
              {councilError && <div className="token-status error">{councilError}</div>}
              {presetStatus && (
                <div className={`token-status ${presetStatus.type}`}>
                  {presetStatus.message}
                </div>
              )}
              {!councilSettings ? (
                <div className="token-status">Loading settings...</div>
              ) : (
                <>
                  <div className="info-text">
                    → Drag cards to reorder. Updates apply to new messages immediately after saving.
                  </div>
                  <div className="info-text stage-info">
                    → Stage builder: drag members between stages, drag stages to reorder, and set prompt + execution mode.
                  </div>
                  <div className="stages-header">
                    <div>
                      <div className="section-title">Council Flow</div>
                      <div className="section-subtitle">Up to 10 stages, 5 members per stage.</div>
                    </div>
                    <button
                      className="small-btn"
                      onClick={handleAddStage}
                      disabled={(councilSettings.stages || []).length >= 10}
                    >
                      Add Stage
                    </button>
                  </div>
                  <div className="stages-grid">
                    {(councilSettings.stages || []).map((stage, stageIndex) => (
                      <div
                        key={stage.id}
                        className="stage-card"
                        draggable
                        onDragStart={() => handleStageDragStart(stageIndex)}
                        onDragOver={(event) => event.preventDefault()}
                        onDrop={() => handleStageDrop(stageIndex)}
                      >
                        <div className="stage-card-header">
                          <div>
                            <div className="stage-kicker">Stage {stageIndex + 1}</div>
                            <input
                              type="text"
                              className="stage-name-input"
                              value={stage.name}
                              onChange={(event) => updateStage(stage.id, { name: event.target.value })}
                            />
                          </div>
                          <button
                            className="remove-btn"
                            onClick={() => handleRemoveStage(stage.id)}
                            title="Remove stage"
                            disabled={(councilSettings.stages || []).length <= 1}
                          >
                            ×
                          </button>
                        </div>
                        <label className="member-label" htmlFor={`stage-${stage.id}-mode`}>
                          Execution
                        </label>
                        <select
                          id={`stage-${stage.id}-mode`}
                          className="control-input"
                          value={stage.execution_mode}
                          onChange={(event) => updateStage(stage.id, { execution_mode: event.target.value })}
                        >
                          <option value="parallel">Parallel</option>
                          <option value="sequential">Sequential</option>
                        </select>
                        <label className="member-label" htmlFor={`stage-${stage.id}-prompt`}>
                          Stage prompt (visible in chat)
                        </label>
                        <textarea
                          id={`stage-${stage.id}-prompt`}
                          className="stage-prompt"
                          rows={3}
                          value={stage.prompt || ''}
                          onChange={(event) => updateStage(stage.id, { prompt: event.target.value })}
                          placeholder="Optional guidance. Supports {question}, {responses}, {response_count}, {response_labels}, {stage1}, {stage2}."
                        />
                        <div className="stage-member-hint">
                          {stage.member_ids.length} / 5 members assigned.
                        </div>
                        <div
                          className="stage-members"
                          onDragOver={(event) => event.preventDefault()}
                          onDrop={() => handleMemberDrop(stage.id)}
                        >
                          {stage.member_ids.map((memberId) => {
                            const member = councilSettings.members.find((entry) => entry.id === memberId);
                            if (!member) return null;
                            return (
                              <div
                                key={memberId}
                                className="stage-member-chip"
                                draggable
                                onDragStart={() => handleMemberDragStart(memberId, stage.id)}
                                onDragEnd={() => setDraggedMember(null)}
                              >
                                <span>{member.alias}</span>
                              </div>
                            );
                          })}
                        </div>
                        <div className="stage-member-hint">
                          Drag members here (max 5).
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="members-grid">
                    {councilSettings.members.map((member, index) => (
                      <div
                        key={member.id}
                        className="member-card"
                        draggable
                        onDragStart={() => handleDragStart(index)}
                        onDragOver={(event) => event.preventDefault()}
                        onDrop={() => handleDrop(index)}
                      >
                        <div className="member-header">
                          <div className="member-number">Member #{index + 1}</div>
                          <button
                            className="remove-btn"
                            onClick={() => handleRemoveMember(member.id)}
                            title="Remove member"
                          >
                            ×
                          </button>
                        </div>
                        <div className="member-alias-section">
                          <span className="member-label">Alias</span>
                          <input
                            type="text"
                            className="member-alias"
                            value={member.alias}
                            onChange={(event) => updateMember(member.id, { alias: event.target.value })}
                          />
                        </div>
                        <span className="member-label">Model</span>
                        <select
                          className="member-model"
                          value={member.model_id}
                          onChange={(event) => updateMember(member.id, { model_id: event.target.value })}
                        >
                          {councilModels.map((model) => (
                            <option key={model.id} value={model.id}>
                              {model.label} ({model.id})
                            </option>
                          ))}
                        </select>
                        <span className="member-label">System Prompt (optional)</span>
                        <textarea
                          className="member-prompt"
                          rows={3}
                          value={member.system_prompt || ''}
                          onChange={(event) =>
                            updateMember(member.id, { system_prompt: event.target.value })
                          }
                          placeholder="Add role-specific guidance for this member..."
                        />
                        <button
                          className={`chairman-btn ${councilSettings.chairman_id === member.id ? 'active' : ''}`}
                          onClick={() =>
                            setCouncilSettings((prev) => ({ ...prev, chairman_id: member.id }))
                          }
                        >
                          {councilSettings.chairman_id === member.id ? 'Chairman' : 'Set as Chairman'}
                        </button>
                      </div>
                    ))}
                    <button
                      type="button"
                      className="member-card add-member-card"
                      onClick={handleAddMember}
                      disabled={councilSettings.members.length >= (councilSettings.max_members || 7)}
                    >
                      <div className="add-icon">+</div>
                      <div className="add-text">Add Member</div>
                    </button>
                  </div>
                  <div className="council-footer">
                    <div className="token-modal-actions">
                      <button type="button" className="token-cancel-btn" onClick={closeCouncilModal}>
                        Cancel
                      </button>
                      <button
                        type="button"
                        className="token-save-btn"
                        onClick={handleSaveCouncil}
                        disabled={isCouncilSaving}
                      >
                        {isCouncilSaving ? 'Saving...' : 'Save Settings'}
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

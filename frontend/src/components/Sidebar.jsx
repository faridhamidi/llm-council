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
  const [regionOptions, setRegionOptions] = useState([]);
  const [selectedRegion, setSelectedRegion] = useState('');
  const [regionStatus, setRegionStatus] = useState(null);
  const [connectionStatus, setConnectionStatus] = useState(null);
  const [isCheckingConnection, setIsCheckingConnection] = useState(false);
  const [isCouncilModalOpen, setIsCouncilModalOpen] = useState(false);
  const [councilSettings, setCouncilSettings] = useState(null);
  const [councilModels, setCouncilModels] = useState([]);
  const [councilError, setCouncilError] = useState(null);
  const [isCouncilSaving, setIsCouncilSaving] = useState(false);
  const [draggedIndex, setDraggedIndex] = useState(null);
  const [draggedStageIndex, setDraggedStageIndex] = useState(null);
  const [draggedMember, setDraggedMember] = useState(null);
  const [dragOverMember, setDragOverMember] = useState(null); // { stageId, memberIndex }
  const [dragOverStage, setDragOverStage] = useState(null); // stageIndex (for stage sort) or stageId (for member drop)
  const [councilPresets, setCouncilPresets] = useState([]);
  const [selectedPresetId, setSelectedPresetId] = useState('');
  const [presetNameInput, setPresetNameInput] = useState('');
  const [presetStatus, setPresetStatus] = useState(null);
  const [speakerModelId, setSpeakerModelId] = useState('');

  const buildDefaultStages = (members, chairmanId) => {
    const memberIds = members.map((member) => member.id);
    const defaultChairman = memberIds.includes(chairmanId) ? chairmanId : memberIds[0] || '';
    return [
      {
        id: 'stage-1',
        name: 'Individual Responses',
        prompt: '',
        execution_mode: 'parallel',
        member_ids: [...memberIds],
      },
      {
        id: 'stage-2',
        name: 'Peer Rankings',
        prompt: '',
        execution_mode: 'parallel',
        member_ids: [...memberIds],
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
      type: stage.type || 'ai',
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
      // Chairman handles follow-ups (context level still configurable)
      speaker_context_level: settings.speaker_context_level || 'full',
    };
  };

  useEffect(() => {
    if (!accessKeyReady) return;
    let isMounted = true;
    const loadSetup = async () => {
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

      try {
        const connectionResponse = await api.getBedrockConnectionStatus();
        if (!isMounted) return;
        setConnectionStatus(connectionResponse);
      } catch (error) {
        if (!isMounted) return;
        setConnectionStatus({
          ok: false,
          error: error.message || 'Failed to check Bedrock connection.',
        });
      }
    };
    loadSetup();
    return () => {
      isMounted = false;
    };
  }, [accessKeyReady]);

  useEffect(() => {
    const isAnyModalOpen = isCouncilModalOpen;
    if (!isAnyModalOpen) return;

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        closeCouncilModal();
      }
    };

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isCouncilModalOpen]);

  const checkBedrockConnection = async () => {
    setIsCheckingConnection(true);
    try {
      const status = await api.getBedrockConnectionStatus();
      setConnectionStatus(status);
    } catch (error) {
      setConnectionStatus({
        ok: false,
        error: error.message || 'Failed to check Bedrock connection.',
      });
    } finally {
      setIsCheckingConnection(false);
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

      const coerced = coerceCouncilSettings(settingsResponse, models);

      // Extract Chairman
      const chairmanId = coerced.chairman_id;
      const chairmanMember = coerced.members.find(m => m.id === chairmanId);
      const visibleMembers = coerced.members.filter(m => m.id !== chairmanId);

      // Extract Speaker Model
      const initialSpeakerModel = chairmanMember ? chairmanMember.model_id : (models[0]?.id || '');
      setSpeakerModelId(initialSpeakerModel);

      // Filter Stages (hide Final Synthesis)
      const visibleStages = (coerced.stages || []).filter(s =>
        s.id !== 'stage-3' && s.name !== 'Final Synthesis'
      );

      setCouncilSettings({
        ...coerced,
        members: visibleMembers,
        stages: visibleStages
      });

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

  const handleAddMemberToStage = (stageId) => {
    setCouncilSettings((prev) => {
      if (!prev) return prev;
      const maxMembers = prev.max_members || 64;
      if (prev.members.length >= maxMembers) return prev;
      const stage = (prev.stages || []).find((s) => s.id === stageId);
      if (!stage) return prev;

      // VALIDATION FIX: Filter out ghost members to get true count
      const validMemberIds = stage.member_ids.filter(mid => prev.members.some(m => m.id === mid));

      if (validMemberIds.length >= 6) return prev;

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
      const nextMembers = [...prev.members, newMember];
      // We use the CLEANED validMemberIds list when appending, effectively healing the stage
      const nextStages = (prev.stages || []).map((s) =>
        s.id === stageId
          ? { ...s, member_ids: [...validMemberIds, newId] }
          : s
      );
      return { ...prev, members: nextMembers, stages: nextStages };
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
      const nextStages = (prev.stages || []).map((stage) => ({
        ...stage,
        member_ids: stage.member_ids.filter((id) => id !== memberId),
      }));
      return { ...prev, members: nextMembers, chairman_id: nextChairman, stages: nextStages };
    });
  };

  const handleRemoveMemberFromStage = (stageId, memberId) => {
    setCouncilSettings((prev) => {
      if (!prev) return prev;
      const nextStages = (prev.stages || []).map((stage) => {
        if (stage.id !== stageId) return stage;
        // Also clean ghosts while we are at it
        const validMemberIds = stage.member_ids.filter(mid => prev.members.some(m => m.id === mid));
        return {
          ...stage,
          member_ids: validMemberIds.filter((id) => id !== memberId),
        };
      });
      return { ...prev, stages: nextStages };
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

  const handleMemberDrop = (targetStageId, targetMemberIndex = null) => {
    setCouncilSettings((prev) => {
      if (!prev || !draggedMember) return prev;

      // If dropping on the same stage, reorder within the stage
      if (draggedMember.stageId === targetStageId && targetMemberIndex !== null) {
        const nextStages = (prev.stages || []).map((stage) => {
          if (stage.id !== targetStageId) return stage;
          const memberIds = [...stage.member_ids];
          const currentIndex = memberIds.indexOf(draggedMember.memberId);
          if (currentIndex === -1 || currentIndex === targetMemberIndex) return stage;
          // Remove from current position and insert at target
          memberIds.splice(currentIndex, 1);
          memberIds.splice(targetMemberIndex, 0, draggedMember.memberId);
          return { ...stage, member_ids: memberIds };
        });
        return { ...prev, stages: nextStages };
      }

      // Moving between different stages
      if (draggedMember.stageId === targetStageId) return prev;

      // 1. Pre-check target stage capacity
      const targetStage = (prev.stages || []).find(s => s.id === targetStageId);
      if (!targetStage) return prev;

      const validTargetMembers = targetStage.member_ids.filter(mid => prev.members.some(m => m.id === mid));
      if (validTargetMembers.length >= 6) {
        // Target is full, abort operation to prevent data loss (member staying in source)
        return prev;
      }

      // 2. Perform the move
      const nextStages = (prev.stages || []).map((stage) => {
        if (stage.id === draggedMember.stageId) {
          return {
            ...stage,
            member_ids: stage.member_ids.filter((id) => id !== draggedMember.memberId),
          };
        }
        if (stage.id === targetStageId) {
          if (stage.member_ids.includes(draggedMember.memberId)) {
            return stage;
          }
          // Use cleaned list from pre-check + new member
          return {
            ...stage,
            member_ids: [...validTargetMembers, draggedMember.memberId],
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
      // Re-construct settings with hidden Chairman and Final Synthesis
      const nextSettingsBase = coerceCouncilSettings(councilSettings, councilModels);

      const visibleMembers = nextSettingsBase.members;
      const visibleMemberIds = new Set(visibleMembers.map((member) => member.id));
      let chairmanId = nextSettingsBase.chairman_id || 'chairman-fixed';
      if (visibleMemberIds.has(chairmanId)) {
        const fallbackId = typeof crypto !== 'undefined' && crypto.randomUUID
          ? crypto.randomUUID()
          : `chairman-${Date.now()}`;
        chairmanId = visibleMemberIds.has('chairman-fixed') ? fallbackId : 'chairman-fixed';
      }

      const chairmanMember = {
        id: chairmanId,
        alias: nextSettingsBase.chairman_label || 'Chairman',
        model_id: speakerModelId,
        system_prompt: '',
      };

      const allMembers = [...visibleMembers, chairmanMember];

      // Re-construct Stages
      const synthesisStage = {
        id: 'stage-3',
        name: 'Final Synthesis',
        prompt: '',
        execution_mode: 'sequential',
        member_ids: [chairmanId]
      };

      const allStages = [...(nextSettingsBase.stages || []), synthesisStage];

      const payload = {
        members: allMembers,
        chairman_id: chairmanId,
        chairman_label: nextSettingsBase.chairman_label || 'Chairman',
        title_model_id: nextSettingsBase.title_model_id,
        use_system_prompt_stage2: nextSettingsBase.use_system_prompt_stage2 ?? true,
        use_system_prompt_stage3: nextSettingsBase.use_system_prompt_stage3 ?? true,
        stages: allStages,
        speaker_context_level: nextSettingsBase.speaker_context_level || 'full',
      };

      await api.updateCouncilSettings(payload);

      // Update local state is tricky because we want to keep the UI "clean"
      // We essentially just keep the current visible state, but we might want to reload to be safe.
      // But for smooth UX, let's just close modal.
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
      await checkBedrockConnection();
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
        <button className="action-btn primary" onClick={() => onNewConversation('council')}>
          <span>+ New Council</span>
        </button>
        <button className="action-btn" onClick={() => onNewConversation('chat')}>
          <span>+ New Chat</span>
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
        <button
          className="action-btn bedrock-update"
          onClick={checkBedrockConnection}
          disabled={isCheckingConnection}
        >
          <span>{isCheckingConnection ? 'Checking...' : 'Check AWS SSO'}</span>
        </button>
        {regionStatus && (
          <div className={`token-status ${regionStatus.type}`}>
            {regionStatus.message}
          </div>
        )}
        {connectionStatus && (
          <div className={`token-status ${connectionStatus.ok ? 'success' : 'error'}`}>
            {connectionStatus.ok
              ? `Connected via ${connectionStatus.mode === 'sso' ? 'AWS SSO' : 'AWS credentials'}${connectionStatus.profile ? ` (${connectionStatus.profile})` : ''}`
              : (connectionStatus.error || 'Bedrock connection unavailable.')}
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
              className={`conversation-item ${conv.id === currentConversationId ? 'active' : ''
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
                {(conv.mode || 'council') === 'chat' ? 'Chat' : 'Council'} • {conv.message_count} messages
              </div>
            </div>
          ))
        )}
      </div>

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
                      Disable system prompts in Rankings & Synthesis
                    </label>
                  </div>
                  <div className="control-row">
                    <span className="control-label">Chairman Context</span>
                    <select
                      className="control-input"
                      value={councilSettings.speaker_context_level || 'full'}
                      onChange={(event) =>
                        setCouncilSettings((prev) => ({ ...prev, speaker_context_level: event.target.value }))
                      }
                    >
                      <option value="minimal">Minimal (Final synthesis only)</option>
                      <option value="standard">Standard (Synthesis + queries)</option>
                      <option value="full">Full (All stages + rankings)</option>
                    </select>
                    <span className="control-help">Context given to Chairman for follow-up questions</span>
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
                  <div className="info-text stage-info">
                    → Configure members directly within each stage. Drag to reorder stages or move members between stages.
                  </div>
                  <div className="stages-header">
                    <div>
                      <div className="section-title">Council Flow</div>
                      <div className="section-subtitle">
                        Up to 10 stages • {councilSettings.members.length} / {councilSettings.max_members || 7} total members
                      </div>
                    </div>
                    <button
                      className="small-btn"
                      onClick={handleAddStage}
                      disabled={(councilSettings.stages || []).length >= 10}
                    >
                      + Add Stage
                    </button>
                  </div>
                  <div className="stages-container">
                    {(councilSettings.stages || []).map((stage, stageIndex) => (
                      <div
                        key={stage.id}
                        className={`stage-card-row ${draggedStageIndex === stageIndex ? 'dragging' : ''} ${(dragOverStage === stageIndex && draggedStageIndex !== null && draggedStageIndex !== stageIndex) ||
                          (dragOverStage === stage.id && draggedMember && draggedMember.stageId !== stage.id)
                          ? 'drag-over'
                          : ''
                          }`}
                        draggable={false}
                        onDragOver={(event) => {
                          event.preventDefault();
                          // Handle stage reordering feedback
                          if (draggedStageIndex !== null && draggedStageIndex !== stageIndex) {
                            setDragOverStage(stageIndex);
                          }
                          // Handle member drop feedback
                          if (draggedMember && draggedMember.stageId !== stage.id) {
                            setDragOverStage(stage.id);
                          }
                        }}
                        onDragLeave={() => setDragOverStage(null)}
                        onDrop={() => {
                          if (draggedStageIndex !== null) {
                            handleStageDrop(stageIndex);
                          } else if (draggedMember) {
                            handleMemberDrop(stage.id);
                          }
                          setDragOverStage(null);
                        }}
                        onDragEnd={() => {
                          setDraggedStageIndex(null);
                          setDragOverStage(null);
                        }}
                      >
                        <div className="stage-row-header">
                          <div className="stage-header-left">
                            <div
                              className="stage-drag-handle"
                              draggable="true"
                              onDragStart={(e) => {
                                e.dataTransfer.effectAllowed = 'move';
                                // Set the drag image to the whole card
                                const card = e.target.closest('.stage-card-row');
                                if (card) {
                                  e.dataTransfer.setDragImage(card, 0, 0);
                                }
                                handleStageDragStart(stageIndex);
                              }}
                            >
                              ⋮⋮
                            </div>
                            <div>
                              <div className="stage-kicker">Stage {stageIndex + 1}</div>
                              <input
                                type="text"
                                className="stage-name-input"
                                value={stage.name}
                                onChange={(event) => updateStage(stage.id, { name: event.target.value })}
                                placeholder="Stage name"
                              />
                            </div>
                          </div>
                          <div className="stage-header-controls">
                            <div className="stage-control-group">
                              <label className="control-label-inline" htmlFor={`stage-${stage.id}-type`}>
                                Type:
                              </label>
                              <select
                                id={`stage-${stage.id}-type`}
                                className="control-input-inline"
                                value={stage.type || 'ai'}
                                onChange={(event) => updateStage(stage.id, { type: event.target.value })}
                              >
                                <option value="ai">AI Council</option>
                                <option value="human">Human Input</option>
                              </select>
                            </div>
                            {(!stage.type || stage.type === 'ai') && (
                              <div className="stage-control-group">
                                <label className="control-label-inline" htmlFor={`stage-${stage.id}-mode`}>
                                  Execution:
                                </label>
                                <select
                                  id={`stage-${stage.id}-mode`}
                                  className="control-input-inline"
                                  value={stage.execution_mode}
                                  onChange={(event) => updateStage(stage.id, { execution_mode: event.target.value })}
                                >
                                  <option value="parallel">Parallel</option>
                                  <option value="sequential">Sequential</option>
                                </select>
                              </div>
                            )}
                            <button
                              className="remove-btn"
                              onClick={() => handleRemoveStage(stage.id)}
                              title="Remove stage"
                              disabled={(councilSettings.stages || []).length <= 1}
                            >
                              ×
                            </button>
                          </div>
                        </div>
                        <div className="stage-prompt-section">
                          <label className="member-label" htmlFor={`stage-${stage.id}-prompt`}>
                            Stage prompt (optional, visible in chat)
                          </label>
                          <textarea
                            id={`stage-${stage.id}-prompt`}
                            className="stage-prompt"
                            rows={2}
                            value={stage.prompt || ''}
                            onChange={(event) => updateStage(stage.id, { prompt: event.target.value })}
                            placeholder="Optional guidance. Supports {question}, {responses}, {response_count}, {response_labels}, {stage1}, {stage2}."
                          />
                        </div>
                        {(!stage.type || stage.type === 'ai') ? (
                          <div className="stage-members-section">
                            <div className="stage-members-header">
                              {/* Calculate valid count for display */}
                              <span className="member-label">
                                Members ({stage.member_ids.filter(mid => councilSettings.members.some(m => m.id === mid)).length} / 6)
                              </span>
                            </div>
                            <div
                              className="stage-members-grid"
                              onDragOver={(event) => event.preventDefault()}
                              onDrop={() => handleMemberDrop(stage.id)}
                            >
                              {stage.member_ids.map((memberId, memberIndex) => {
                                const member = councilSettings.members.find((entry) => entry.id === memberId);
                                if (!member) return null;
                                const isDragOver = dragOverMember?.stageId === stage.id && dragOverMember?.memberIndex === memberIndex;
                                return (
                                  <div
                                    key={memberId}
                                    className={`member-card-inline ${draggedMember?.memberId === memberId ? 'dragging' : ''} ${isDragOver ? 'drag-over' : ''}`}
                                    draggable={false}
                                    onDragEnd={(e) => {
                                      e.stopPropagation();
                                      setDraggedMember(null);
                                      setDragOverMember(null);
                                    }}
                                    onDragOver={(e) => {
                                      e.preventDefault();
                                      e.stopPropagation();
                                      if (draggedMember && draggedMember.stageId === stage.id && draggedMember.memberId !== memberId) {
                                        setDragOverMember({ stageId: stage.id, memberIndex });
                                      }
                                    }}
                                    onDragLeave={(e) => {
                                      e.stopPropagation();
                                      setDragOverMember(null);
                                    }}
                                    onDrop={(e) => {
                                      e.stopPropagation();
                                      handleMemberDrop(stage.id, memberIndex);
                                      setDragOverMember(null);
                                    }}
                                  >
                                    <div className="member-card-inline-header">
                                      <div
                                        className="member-drag-handle"
                                        draggable="true"
                                        onDragStart={(e) => {
                                          e.stopPropagation();
                                          e.dataTransfer.effectAllowed = 'move';
                                          const card = e.target.closest('.member-card-inline');
                                          if (card) {
                                            e.dataTransfer.setDragImage(card, 0, 0);
                                          }
                                          handleMemberDragStart(memberId, stage.id);
                                        }}
                                      >
                                        ⋮⋮
                                      </div>
                                      <span className="member-number">{memberIndex + 1}</span>
                                      <input
                                        type="text"
                                        className="member-alias-inline"
                                        value={member.alias}
                                        onChange={(event) => updateMember(member.id, { alias: event.target.value })}
                                        placeholder="Member alias"
                                      />
                                      <button
                                        className="remove-btn-small"
                                        onClick={() => handleRemoveMemberFromStage(stage.id, member.id)}
                                        title="Remove from stage"
                                      >
                                        ×
                                      </button>
                                    </div>
                                    <select
                                      className="member-model-inline"
                                      value={member.model_id}
                                      onChange={(event) => updateMember(member.id, { model_id: event.target.value })}
                                    >
                                      {councilModels.map((model) => (
                                        <option key={model.id} value={model.id}>
                                          {model.label}
                                        </option>
                                      ))}
                                    </select>
                                    <textarea
                                      className="member-prompt-inline"
                                      rows={2}
                                      value={member.system_prompt || ''}
                                      onChange={(event) =>
                                        updateMember(member.id, { system_prompt: event.target.value })
                                      }
                                      placeholder="System prompt (optional)..."
                                    />
                                    {/* Chairman button removed */}
                                  </div>
                                );
                              })}

                              {/* Only show add button if we haven't reached the limit of 6 */
                                stage.member_ids.filter(mid => councilSettings.members.some(m => m.id === mid)).length < 6 && (
                                  <button
                                    className="add-member-btn-inline"
                                    onClick={() => handleAddMemberToStage(stage.id)}
                                    disabled={
                                      councilSettings.members.length >= (councilSettings.max_members || 64)
                                    }
                                    title="Add member to this stage"
                                  >
                                    <span className="add-icon-inline">+</span>
                                    <span>Add Member</span>
                                  </button>
                                )}
                            </div>
                          </div>
                        ) : null}
                      </div>
                    ))}
                    {/* Static Final Synthesis Stage */}
                    <div className="stage-card-row static-stage">
                      <div className="stage-row-header">
                        <div className="stage-header-left">
                          <div className="stage-kicker">Final Stage</div>
                          <div className="stage-name-static">Final Synthesis (by Speaker)</div>
                        </div>
                        <div className="stage-header-controls">
                          <span className="static-badge">System</span>
                        </div>
                      </div>
                      <div className="stage-members-section">
                        <div className="stage-members-header">
                          <span className="member-label">Speaker Configuration</span>
                        </div>
                        <div className="stage-members-grid" style={{ gridTemplateColumns: '1fr', borderStyle: 'solid', borderColor: 'var(--accent-teal)' }}>
                          <div className="member-card-inline" style={{ borderColor: 'transparent', boxShadow: 'none', background: 'transparent', padding: 0 }}>
                            <div className="member-card-inline-header">
                              <div className="member-alias-inline" style={{ background: 'transparent', border: 'none', paddingLeft: 0, fontWeight: 700, fontSize: '15px' }}>
                                Council Speaker / Chairman
                              </div>
                            </div>
                            <select
                              className="member-model-inline"
                              value={speakerModelId}
                              onChange={(event) => setSpeakerModelId(event.target.value)}
                              style={{ borderColor: 'var(--accent-teal)' }}
                            >
                              {councilModels.map((model) => (
                                <option key={model.id} value={model.id}>
                                  {model.label}
                                </option>
                              ))}
                            </select>
                            <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                              The Speaker synthesizes the final answer and handles follow-up questions.
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="members-grid" style={{ display: 'none' }}>
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
                        {/* Chairman button removed */}
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
      )
      }
    </div >
  );
}

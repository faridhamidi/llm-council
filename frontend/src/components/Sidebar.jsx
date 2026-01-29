import { useState, useEffect } from 'react';
import { api } from '../api';
import './Sidebar.css';

export default function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  onDeleteConversation,
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
    return {
      ...settings,
      members: nextMembers,
      chairman_id: nextChairmanId,
      title_model_id: nextTitleModelId,
    };
  };

  useEffect(() => {
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
  }, []);

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
    setIsCouncilModalOpen(true);
    try {
      const [settingsResponse, modelsResponse] = await Promise.all([
        api.getCouncilSettings(),
        api.listBedrockModels(),
      ]);
      const models = modelsResponse.models || [];
      setCouncilModels(models);
      setCouncilSettings(coerceCouncilSettings(settingsResponse, models));
    } catch (error) {
      setCouncilError(error.message || 'Failed to load council settings.');
    }
  };

  const closeCouncilModal = () => {
    setIsCouncilModalOpen(false);
    setDraggedIndex(null);
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

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <h1>LLM Council</h1>
        <button className="new-conversation-btn" onClick={onNewConversation}>
          + New Conversation
        </button>
        <button className="token-refresh-btn" onClick={openTokenModal}>
          Refresh Bedrock Token
        </button>
        <button className="token-refresh-btn" onClick={openCouncilModal}>
          Council Settings
        </button>
        <div className="region-selector">
          <label htmlFor="bedrock-region-select">Bedrock Region</label>
          <div className="region-row">
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
            <button className="region-apply-btn" onClick={handleRegionUpdate}>
              Update
            </button>
          </div>
        </div>
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
            <div className="token-modal-header">
              <h3>Council Members</h3>
              <button className="token-modal-close" onClick={closeCouncilModal}>
                ×
              </button>
            </div>
            <div className="council-meta">
              {councilSettings && (
                <span>
                  {councilSettings.members.length} / {councilSettings.max_members || 7} members
                </span>
              )}
              <button
                className="region-apply-btn"
                onClick={handleAddMember}
                disabled={!councilSettings || councilSettings.members.length >= (councilSettings.max_members || 7)}
              >
                + Add member
              </button>
            </div>
            {councilError && <div className="token-status error">{councilError}</div>}
            {!councilSettings ? (
              <div className="token-status">Loading settings...</div>
            ) : (
              <>
                <div className="token-status hint">
                  Drag cards to reorder. Updates apply to new messages immediately after saving.
                </div>
                <div className="council-grid">
                  {councilSettings.members.map((member, index) => (
                    <div
                      key={member.id}
                      className="council-card"
                      draggable
                      onDragStart={() => handleDragStart(index)}
                      onDragOver={(event) => event.preventDefault()}
                      onDrop={() => handleDrop(index)}
                    >
                      <div className="council-card-header">
                        <span className="drag-handle">⋮⋮</span>
                        <span className="council-card-title">Member {index + 1}</span>
                        <button
                          className="conversation-delete-btn"
                          onClick={() => handleRemoveMember(member.id)}
                          title="Remove member"
                        >
                          ×
                        </button>
                      </div>
                      <label>
                        Alias
                        <input
                          type="text"
                          value={member.alias}
                          onChange={(event) => updateMember(member.id, { alias: event.target.value })}
                        />
                      </label>
                      <label>
                        Model
                        <select
                          value={member.model_id}
                          onChange={(event) => updateMember(member.id, { model_id: event.target.value })}
                        >
                          {councilModels.map((model) => (
                            <option key={model.id} value={model.id}>
                              {model.label} ({model.id})
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        System prompt (optional)
                        <textarea
                          rows={3}
                          value={member.system_prompt || ''}
                          onChange={(event) =>
                            updateMember(member.id, { system_prompt: event.target.value })
                          }
                          placeholder="Add role-specific guidance for this member..."
                        />
                      </label>
                      <button
                        className={`chairman-btn ${councilSettings.chairman_id === member.id ? 'active' : ''}`}
                        onClick={() =>
                          setCouncilSettings((prev) => ({ ...prev, chairman_id: member.id }))
                        }
                      >
                        {councilSettings.chairman_id === member.id ? 'Chairman' : 'Set Chairman'}
                      </button>
                    </div>
                  ))}
                </div>
                <div className="council-footer">
                  <label className="title-model">
                    Title model
                    <select
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
                  </label>
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
      )}
    </div>
  );
}

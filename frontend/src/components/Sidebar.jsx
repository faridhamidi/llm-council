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

  const handleRegionUpdate = async () => {
    if (!selectedRegion) {
      setRegionStatus({ type: 'error', message: 'Select a region first.' });
      return;
    }
    try {
      await api.updateBedrockRegion(selectedRegion);
      setRegionStatus({ type: 'success', message: `Region set to ${selectedRegion}` });
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
    </div>
  );
}

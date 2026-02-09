import { useState, useEffect, useRef } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import CouncilStudio from './components/CouncilStudio';
import { api, setAccessKey, clearAccessKey } from './api';
import logoMark from './assets/NetZero2050-logo.svg';
import './App.css';

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [streamController, setStreamController] = useState(null);
  const [streamingConversationId, setStreamingConversationId] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);
  const [undoSecondsLeft, setUndoSecondsLeft] = useState(0);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isCouncilStudioOpen, setIsCouncilStudioOpen] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [hasPin, setHasPin] = useState(false);
  const [authPolicy, setAuthPolicy] = useState(null);
  const [authSetupRequired, setAuthSetupRequired] = useState(false);
  const [accessKeyPresent, setAccessKeyPresent] = useState(false);
  const [pinInput, setPinInput] = useState('');
  const [pinError, setPinError] = useState('');
  const [isSettingPin, setIsSettingPin] = useState(false);
  const [remainingMessages, setRemainingMessages] = useState(null);
  const conversationCacheRef = useRef({});
  const currentConversationIdRef = useRef(null);
  const currentConversationRef = useRef(null);
  const deleteTimerRef = useRef(null);
  const deleteIntervalRef = useRef(null);

  useEffect(() => {
    currentConversationIdRef.current = currentConversationId;
  }, [currentConversationId]);

  useEffect(() => {
    currentConversationRef.current = currentConversation;
  }, [currentConversation]);

  // Load conversations on mount
  useEffect(() => {
    const bootstrapAuth = async () => {
      try {
        clearAccessKey();
        setAccessKeyPresent(false);
        const status = await api.getAuthStatus();
        setAuthPolicy(status.policy ?? null);
        setAuthSetupRequired(Boolean(status.requires_setup));
        setHasPin(Boolean(status.has_pin));
        if (status.policy === 'disabled') {
          setAccessKeyPresent(true);
          loadConversations();
        } else if (!status.has_pin && !status.requires_setup) {
          loadConversations();
        }
      } catch (error) {
        console.error('Failed to load auth status:', error);
      } finally {
        setAuthChecked(true);
      }
    };
    bootstrapAuth();
  }, []);

  // Load conversation details when selected
  useEffect(() => {
    if (currentConversationId) {
      loadConversation(currentConversationId);
    }
  }, [currentConversationId]);

  useEffect(() => {
    if (!authChecked) return;
    if (authPolicy === 'disabled') {
      loadConversations();
      return;
    }
    if (hasPin && accessKeyPresent) {
      loadConversations();
    }
  }, [authChecked, hasPin, accessKeyPresent, authPolicy]);

  const loadConversations = async () => {
    try {
      const convs = await api.listConversations();
      setConversations(convs);
    } catch (error) {
      if (error.message === 'Unauthorized') {
        clearAccessKey();
        setAccessKeyPresent(false);
        setPinError('Invalid PIN. Please try again.');
        setConversations([]);
        setCurrentConversationId(null);
        setCurrentConversation(null);
      } else {
        console.error('Failed to load conversations:', error);
      }
    }
  };

  const loadConversation = async (id) => {
    const cached = conversationCacheRef.current[id];
    if (cached && streamingConversationId === id) {
      setCurrentConversation(cached);
      return;
    }
    try {
      const conv = await api.getConversation(id);
      conversationCacheRef.current[id] = conv;
      setCurrentConversation(conv);

      // Also fetch conversation info to get remaining messages count
      try {
        const info = await api.getConversationInfo(id);
        if (info && info.remaining_messages !== undefined) {
          setRemainingMessages(info.remaining_messages);
        }
      } catch (infoError) {
        console.error('Failed to load conversation info:', infoError);
      }
    } catch (error) {
      console.error('Failed to load conversation:', error);
    }
  };

  const updateConversationById = (id, updater) => {
    const cached = conversationCacheRef.current[id];
    const base = cached || (currentConversationIdRef.current === id
      ? currentConversationRef.current
      : null);
    if (!base) return;
    const next = updater(base);
    conversationCacheRef.current[id] = next;
    if (currentConversationIdRef.current === id) {
      setCurrentConversation(next);
    }
  };

  const updateLastAssistantMessage = (conversation, updater) => {
    if (!conversation?.messages?.length) return conversation;
    const messages = [...conversation.messages];
    const last = messages[messages.length - 1];
    const nextLast = updater({
      ...last,
    });
    messages[messages.length - 1] = nextLast;
    return { ...conversation, messages };
  };

  const upsertStage = (stages = [], stageData = {}) => {
    const nextStages = [...stages];
    const index = stageData.index;
    if (index !== undefined && index !== null) {
      nextStages[index] = { ...(nextStages[index] || {}), ...stageData };
      return nextStages;
    }
    const idIndex = stageData.id
      ? nextStages.findIndex((stage) => stage.id === stageData.id)
      : -1;
    if (idIndex >= 0) {
      nextStages[idIndex] = { ...nextStages[idIndex], ...stageData };
      return nextStages;
    }
    nextStages.push(stageData);
    return nextStages;
  };

  const applyStageMemberDelta = (message, stageDelta = {}) => {
    const stageKind = stageDelta.kind || 'responses';
    const stageStub = {
      index: stageDelta.index,
      id: stageDelta.id,
      name: stageDelta.name,
      kind: stageKind,
      status: 'running',
    };
    const nextStages = upsertStage(message.stages, stageStub);
    const stageIndex = stageDelta.index ?? nextStages.findIndex((stage) => stage.id === stageDelta.id);
    if (stageIndex === undefined || stageIndex === null || stageIndex < 0) {
      return { ...message, stages: nextStages };
    }

    const stage = { ...(nextStages[stageIndex] || {}), ...stageStub };
    const deltaText = stageDelta.delta || '';
    const memberIndex = stageDelta.member_index ?? 0;
    const memberName = stageDelta.member || `Member ${memberIndex + 1}`;

    if (stageKind === 'synthesis') {
      const current = (stage.results && typeof stage.results === 'object') ? stage.results : {};
      stage.results = {
        ...current,
        model: current.model || memberName,
        response: `${current.response || ''}${deltaText}`,
      };
    } else if (stageKind === 'rankings') {
      const current = Array.isArray(stage.results) ? [...stage.results] : [];
      const existing = current[memberIndex] || {
        model: memberName,
        ranking: '',
        parsed_ranking: [],
      };
      current[memberIndex] = {
        ...existing,
        model: existing.model || memberName,
        ranking: `${existing.ranking || ''}${deltaText}`,
      };
      stage.results = current;
    } else {
      const current = Array.isArray(stage.results) ? [...stage.results] : [];
      const existing = current[memberIndex] || {
        model: memberName,
        response: '',
        status: 'ok',
      };
      current[memberIndex] = {
        ...existing,
        model: existing.model || memberName,
        response: `${existing.response || ''}${deltaText}`,
        status: existing.status || 'ok',
      };
      stage.results = current;
    }

    nextStages[stageIndex] = stage;
    return { ...message, stages: nextStages };
  };

  const clearDeleteTimers = () => {
    if (deleteTimerRef.current) {
      clearTimeout(deleteTimerRef.current);
      deleteTimerRef.current = null;
    }
    if (deleteIntervalRef.current) {
      clearInterval(deleteIntervalRef.current);
      deleteIntervalRef.current = null;
    }
  };

  const handleDeleteConversation = async (id) => {
    if (!id) return;

    clearDeleteTimers();
    const conversationIndex = conversations.findIndex((conv) => conv.id === id);
    const conversationMeta = conversations.find((conv) => conv.id === id);
    const wasActive = currentConversationId === id;
    setPendingDelete({ id, conversationIndex, conversationMeta, wasActive });
    setUndoSecondsLeft(10);

    setConversations((prev) => prev.filter((conv) => conv.id !== id));
    if (conversationCacheRef.current[id]) {
      const nextCache = { ...conversationCacheRef.current };
      delete nextCache[id];
      conversationCacheRef.current = nextCache;
    }
    if (currentConversationId === id) {
      setCurrentConversationId(null);
      setCurrentConversation(null);
    }

    deleteIntervalRef.current = setInterval(() => {
      setUndoSecondsLeft((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    deleteTimerRef.current = setTimeout(async () => {
      try {
        await api.deleteConversation(id);
      } catch (error) {
        console.error('Failed to delete conversation:', error);
        if (conversationMeta) {
          setConversations((prev) => {
            const next = [...prev];
            const insertAt = Math.min(
              Math.max(conversationIndex, 0),
              next.length
            );
            next.splice(insertAt, 0, conversationMeta);
            return next;
          });
        } else {
          loadConversations();
        }
      } finally {
        setPendingDelete(null);
        setUndoSecondsLeft(0);
        clearDeleteTimers();
      }
    }, 10000);
  };

  const handleUndoDelete = async () => {
    if (!pendingDelete?.id) return;
    const { id, conversationMeta, conversationIndex, wasActive } = pendingDelete;
    setPendingDelete(null);
    setUndoSecondsLeft(0);
    clearDeleteTimers();
    if (conversationMeta) {
      setConversations((prev) => {
        const next = [...prev];
        const insertAt = Math.min(
          Math.max(conversationIndex, 0),
          next.length
        );
        next.splice(insertAt, 0, conversationMeta);
        return next;
      });
    } else {
      loadConversations();
    }
    if (wasActive) {
      setCurrentConversationId(id);
    }
  };

  const handleConfirmDelete = async () => {
    if (!pendingDelete?.id) return;
    const { id, conversationMeta, conversationIndex } = pendingDelete;
    setPendingDelete(null);
    setUndoSecondsLeft(0);
    clearDeleteTimers();
    try {
      await api.deleteConversation(id);
    } catch (error) {
      console.error('Failed to delete conversation:', error);
      if (conversationMeta) {
        setConversations((prev) => {
          const next = [...prev];
          const insertAt = Math.min(
            Math.max(conversationIndex, 0),
            next.length
          );
          next.splice(insertAt, 0, conversationMeta);
          return next;
        });
      } else {
        loadConversations();
      }
    }
  };

  const handleNewConversation = async (mode = 'council') => {
    try {
      const newConv = await api.createConversation(mode);
      setConversations([
        {
          id: newConv.id,
          created_at: newConv.created_at,
          title: newConv.title,
          mode: newConv.mode || mode,
          message_count: 0,
        },
        ...conversations,
      ]);
      conversationCacheRef.current[newConv.id] = newConv;
      setCurrentConversation(newConv);
      // Keep frontend optimistic counter aligned with backend's temporary chat cap.
      setRemainingMessages(mode === 'chat' ? 100 : null);
      setCurrentConversationId(newConv.id);
      setIsCouncilStudioOpen(false);
      setIsSidebarOpen(false);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = (id) => {
    setCurrentConversationId(id);
    setIsCouncilStudioOpen(false);
    setIsSidebarOpen(false);
  };

  const handleSendMessage = async (content, forceCouncil = false) => {
    if (!currentConversationId) return;

    const targetConversationId = currentConversationId;
    const targetConversation = conversationCacheRef.current[targetConversationId]
      || (currentConversationIdRef.current === targetConversationId ? currentConversationRef.current : null);
    const conversationMode = targetConversation?.mode || 'council';
    setStreamingConversationId(targetConversationId);
    const controller = new AbortController();
    setStreamController(controller);
    try {
      // Optimistically add user message to UI
      const userMessage = { role: 'user', content };
      const assistantMessage = conversationMode === 'chat'
        ? {
          role: 'assistant',
          message_type: 'speaker',
          model: 'Assistant',
          response: '',
          speaker_response: '',
        }
        : {
          role: 'assistant',
          message_type: 'council',
          stages: [],
        };
      updateConversationById(targetConversationId, (prev) => ({
        ...prev,
        messages: [...prev.messages, userMessage, assistantMessage],
      }));

      // Send message with streaming
      await api.sendMessageStream(
        targetConversationId,
        content,
        (eventType, event) => {
          switch (eventType) {
            case 'stage_start':
              updateConversationById(targetConversationId, (prev) =>
                updateLastAssistantMessage(prev, (lastMsg) => ({
                  ...lastMsg,
                  stages: upsertStage(lastMsg.stages, {
                    ...event.data,
                    status: 'running',
                  }),
                }))
              );
              break;

            case 'stage_complete':
              updateConversationById(targetConversationId, (prev) =>
                updateLastAssistantMessage(prev, (lastMsg) => ({
                  ...lastMsg,
                  stages: upsertStage(lastMsg.stages, {
                    ...event.data,
                    status: 'complete',
                  }),
                }))
              );
              break;
            case 'stage_member_delta':
              updateConversationById(targetConversationId, (prev) =>
                updateLastAssistantMessage(prev, (lastMsg) =>
                  applyStageMemberDelta(lastMsg, event.data)
                )
              );
              break;
            case 'speaker_delta':
              updateConversationById(targetConversationId, (prev) =>
                updateLastAssistantMessage(prev, (lastMsg) => {
                  const existing = lastMsg?.response || lastMsg?.speaker_response || '';
                  const delta = event?.data?.delta || '';
                  return {
                    ...lastMsg,
                    message_type: 'speaker',
                    model: lastMsg?.model || (conversationMode === 'chat' ? 'Assistant' : 'Chairman'),
                    response: `${existing}${delta}`,
                    speaker_response: `${existing}${delta}`,
                    error: false,
                    stages: [],
                  };
                })
              );
              break;
            case 'speaker_complete':
              updateConversationById(targetConversationId, (prev) =>
                updateLastAssistantMessage(prev, (lastMsg) => ({
                  ...lastMsg,
                  message_type: 'speaker',
                  model: event?.data?.model || 'Chairman',
                  response: event?.data?.response || '',
                  speaker_response: event?.data?.response || '',
                  error: event?.data?.error || false,
                  stages: [],
                }))
              );
              if (event.remaining_messages !== undefined) {
                setRemainingMessages(event.remaining_messages);
              }
              break;

            case 'title_complete':
              // Reload conversations to get updated title
              loadConversations();
              break;

            case 'complete':
              // Stream complete, reload conversations list
              loadConversations();
              api.getConversationInfo(targetConversationId)
                .then((info) => {
                  if (info && info.remaining_messages !== undefined) {
                    setRemainingMessages(info.remaining_messages);
                  }
                })
                .catch(() => { });
              setStreamController(null);
              setStreamingConversationId(null);
              break;

            case 'error':
              console.error('Stream error:', event.message);
              setStreamController(null);
              setStreamingConversationId(null);
              break;
            case 'cancelled':
              updateConversationById(targetConversationId, (prev) =>
                updateLastAssistantMessage(prev, (lastMsg) => ({
                  ...lastMsg,
                  stages: (lastMsg.stages || []).map((stage) =>
                    stage.status === 'running' ? { ...stage, status: 'cancelled' } : stage
                  ),
                }))
              );
              setStreamController(null);
              setStreamingConversationId(null);
              break;

            default:
              console.log('Unknown event type:', eventType);
          }
        },
        { signal: controller.signal, forceCouncil }
      );
    } catch (error) {
      if (error.name === 'AbortError') {
        updateConversationById(targetConversationId, (prev) =>
          updateLastAssistantMessage(prev, (lastMsg) => ({
            ...lastMsg,
            stages: (lastMsg.stages || []).map((stage) =>
              stage.status === 'running' ? { ...stage, status: 'cancelled' } : stage
            ),
          }))
        );
      } else {
        console.error('Failed to send message:', error);
        // Remove optimistic messages on error
        const errorMessage = `Error: ${error.message}`;

        updateConversationById(targetConversationId, (prev) => {
          const messages = [...prev.messages];
          // Remove the loading assistant message
          messages.pop();
          // Add error message from system
          messages.push({
            role: 'assistant',
            message_type: 'speaker',
            model: 'System',
            response: errorMessage,
            error: true,
          });
          return { ...prev, messages };
        });
      }
      setStreamController(null);
      setStreamingConversationId(null);
    }
  };

  const handleStop = () => {
    if (streamController) {
      streamController.abort();
    }
    if (streamingConversationId) {
      api.cancelMessageStream(streamingConversationId).catch((error) => {
        console.error('Failed to cancel stream:', error);
      });
    }
  };

  const handleRetry = async () => {
    if (!currentConversationId) return;
    try {
      const response = await api.retryMessage(currentConversationId);
      if (response.remaining_messages !== undefined) {
        setRemainingMessages(response.remaining_messages);
      }
      loadConversation(currentConversationId);
    } catch (error) {
      console.error('Failed to retry message:', error);
    }
  };

  const handleResumeCouncil = async (humanInput) => {
    if (!currentConversationId) return;
    try {
      // Optimistically update the UI if needed, or just set loading state
      // For now, we'll rely on the global isLoading check which we can trigger by
      // mocking a streaming state or adding a separate loading state.
      // Since resume is not streaming, we can just await it.

      // Manually set loading on the last message
      updateConversationById(currentConversationId, (prev) =>
        updateLastAssistantMessage(prev, (lastMsg) => ({
          ...lastMsg,
          stages: (lastMsg.stages || []).map((stage) => ({ ...stage, status: 'running' })),
        }))
      );

      const response = await api.resumeCouncil(currentConversationId, humanInput);

      // Update the conversation with the new results
      // response contains the full message object (stages + metadata).

      updateConversationById(currentConversationId, (prev) =>
        updateLastAssistantMessage(prev, (lastMsg) => ({
          ...lastMsg,
          stages: response.stages || [],
        }))
      );

    } catch (error) {
      console.error('Failed to resume council:', error);
      // Revert loading state
      updateConversationById(currentConversationId, (prev) =>
        updateLastAssistantMessage(prev, (lastMsg) => ({
          ...lastMsg,
          stages: (lastMsg.stages || []).map((stage) =>
            stage.status === 'running' ? { ...stage, status: 'cancelled' } : stage
          ),
        }))
      );
    }
  };

  const handlePinSubmit = async (event) => {
    event.preventDefault();
    const trimmed = pinInput.trim();
    if (!trimmed) {
      setPinError('PIN is required.');
      return;
    }

    setPinError('');
    if (!hasPin) {
      try {
        setIsSettingPin(true);
        await api.setupAuthPin(trimmed);
        setAccessKey(trimmed);
        setAccessKeyPresent(true);
        setHasPin(true);
        setAuthPolicy('required');
        setPinInput('');
        loadConversations();
      } catch (error) {
        setPinError(error.message || 'Failed to set PIN.');
      } finally {
        setIsSettingPin(false);
      }
      return;
    }

    setAccessKey(trimmed);
    setAccessKeyPresent(true);
    setPinInput('');
    loadConversations();
  };

  const isAuthorized = authChecked && (authPolicy === 'disabled' || (hasPin && accessKeyPresent));
  const requiresPin = authPolicy === 'required';

  const handlePolicyChoice = async (enabled) => {
    try {
      setIsSettingPin(true);
      const response = await api.setAuthPolicy(enabled);
      setAuthPolicy(response.policy);
      setAuthSetupRequired(false);
      setPinError('');
      if (response.policy === 'disabled') {
        setHasPin(false);
        setAccessKeyPresent(true);
        loadConversations();
      }
    } catch (error) {
      setPinError(error.message || 'Failed to set PIN policy.');
    } finally {
      setIsSettingPin(false);
    }
  };

  return (
    <div className={`app app-container ${isSidebarOpen ? 'sidebar-open' : ''}`}>
      <div className="sidebar-panel">
        <div className="mobile-sidebar-header">
          <button
            className="mobile-sidebar-close"
            onClick={() => setIsSidebarOpen(false)}
            aria-label="Close sidebar"
          >
            ×
          </button>
        </div>
        <Sidebar
          conversations={conversations}
          currentConversationId={currentConversationId}
          onSelectConversation={handleSelectConversation}
          onNewConversation={handleNewConversation}
          onDeleteConversation={handleDeleteConversation}
          onOpenCouncilStudio={() => setIsCouncilStudioOpen(true)}
          accessKeyReady={authChecked && (authPolicy === 'disabled' || isAuthorized)}
        />
      </div>
      <div className="chat-panel">
        <div className="mobile-topbar">
          <button
            className="sidebar-toggle"
            onClick={() => setIsSidebarOpen(true)}
            aria-label="Open sidebar"
          >
            Menu
          </button>
          <div className="mobile-title">LLM Council</div>
        </div>
        {isCouncilStudioOpen ? (
          <CouncilStudio onClose={() => setIsCouncilStudioOpen(false)} />
        ) : (
          <ChatInterface
            conversation={currentConversation}
            onSendMessage={handleSendMessage}
            onStop={handleStop}
            onRetry={handleRetry}
            onResume={handleResumeCouncil}
            isLoading={streamingConversationId === currentConversationId}
            remainingMessages={remainingMessages}
          />
        )}
      </div>
      <button
        className="sidebar-overlay"
        type="button"
        onClick={() => setIsSidebarOpen(false)}
        aria-hidden={!isSidebarOpen}
        tabIndex={isSidebarOpen ? 0 : -1}
      />
      {!authChecked && (
        <div className="pin-backdrop">
          <div className="pin-modal">
            <div className="pin-title">Checking access…</div>
            <div className="pin-subtitle">Preparing secure session.</div>
          </div>
        </div>
      )}
      {authChecked && authSetupRequired && (
        <div className="pin-backdrop">
          <div className="pin-modal">
            <div className="pin-header">
              <div className="pin-logo">
                <img src={logoMark} alt="" />
              </div>
              <div>
                <div className="pin-title">Secure this deployment?</div>
                <div className="pin-subtitle">
                  Choose whether this deployment should require a PIN. This choice is stored in the database and will
                  persist until the DB is deleted or reset.
                </div>
              </div>
            </div>
            {pinError && <div className="pin-error">{pinError}</div>}
            <div className="pin-hint">
              Tip: Enable PIN if you are exposing the app beyond your local machine.
            </div>
            <div className="pin-choice-actions">
              <button
                type="button"
                className="pin-submit"
                onClick={() => handlePolicyChoice(true)}
                disabled={isSettingPin}
              >
                Require PIN
              </button>
              <button
                type="button"
                className="pin-skip"
                onClick={() => handlePolicyChoice(false)}
                disabled={isSettingPin}
              >
                Continue without PIN
              </button>
            </div>
          </div>
        </div>
      )}
      {authChecked && !authSetupRequired && requiresPin && !isAuthorized && (
        <div className="pin-backdrop">
          <form className="pin-modal" onSubmit={handlePinSubmit}>
            <div className="pin-header">
              <div className="pin-logo">
                <img src={logoMark} alt="" />
              </div>
              <div>
                <div className="pin-title">
                  {hasPin ? 'Enter Access PIN' : 'Set Access PIN'}
                </div>
                <div className="pin-subtitle">
                  {hasPin
                    ? 'This app requires a PIN to continue.'
                    : 'Create a PIN to protect access to the backend.'}
                </div>
              </div>
            </div>
            <input
              type="password"
              className="pin-input"
              placeholder="PIN"
              value={pinInput}
              onChange={(event) => setPinInput(event.target.value)}
              autoFocus
            />
            {pinError && <div className="pin-error">{pinError}</div>}
            <div className="pin-hint">
              {hasPin ? 'PINs are stored securely (hashed) in the database.' : 'Choose at least 4 characters.'}
            </div>
            <button type="submit" className="pin-submit" disabled={isSettingPin}>
              {isSettingPin ? 'Saving...' : 'Continue'}
            </button>
          </form>
        </div>
      )}
      {pendingDelete && (
        <div className="undo-toast">
          <div className="undo-message">
            Conversation removed.
            {undoSecondsLeft > 0 && (
              <span className="undo-countdown">
                Deleting in {undoSecondsLeft}s
              </span>
            )}
          </div>
          <div className="undo-actions">
            <button className="undo-secondary" onClick={handleUndoDelete}>
              Undo
            </button>
            <button className="undo-primary" onClick={handleConfirmDelete}>
              Delete now
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;

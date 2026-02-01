import { useState, useEffect, useRef } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
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
      loading: last?.loading ? { ...last.loading } : undefined,
    });
    messages[messages.length - 1] = nextLast;
    return { ...conversation, messages };
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

  const handleNewConversation = async () => {
    try {
      const newConv = await api.createConversation();
      setConversations([
        { id: newConv.id, created_at: newConv.created_at, message_count: 0 },
        ...conversations,
      ]);
      setCurrentConversationId(newConv.id);
      setIsSidebarOpen(false);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = (id) => {
    setCurrentConversationId(id);
    setIsSidebarOpen(false);
  };

  const handleSendMessage = async (content) => {
    if (!currentConversationId) return;

    const targetConversationId = currentConversationId;
    setStreamingConversationId(targetConversationId);
    const controller = new AbortController();
    setStreamController(controller);
    try {
      // Optimistically add user message to UI
      const userMessage = { role: 'user', content };
      const assistantMessage = {
        role: 'assistant',
        stage1: null,
        stage2: null,
        stage3: null,
        metadata: null,
        loading: {
          stage1: false,
          stage2: false,
          stage3: false,
        },
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
            case 'stage1_start':
              updateConversationById(targetConversationId, (prev) =>
                updateLastAssistantMessage(prev, (lastMsg) => {
                  if (lastMsg.loading) {
                    lastMsg.loading.stage1 = true;
                  }
                  return lastMsg;
                })
              );
              break;

            case 'stage1_complete':
              updateConversationById(targetConversationId, (prev) =>
                updateLastAssistantMessage(prev, (lastMsg) => {
                  lastMsg.stage1 = event.data;
                  if (lastMsg.loading) {
                    lastMsg.loading.stage1 = false;
                  }
                  return lastMsg;
                })
              );
              break;

            case 'stage2_start':
              updateConversationById(targetConversationId, (prev) =>
                updateLastAssistantMessage(prev, (lastMsg) => {
                  if (lastMsg.loading) {
                    lastMsg.loading.stage2 = true;
                  }
                  return lastMsg;
                })
              );
              break;

            case 'stage2_complete':
              updateConversationById(targetConversationId, (prev) =>
                updateLastAssistantMessage(prev, (lastMsg) => {
                  lastMsg.stage2 = event.data;
                  lastMsg.metadata = event.metadata;
                  if (lastMsg.loading) {
                    lastMsg.loading.stage2 = false;
                  }
                  return lastMsg;
                })
              );
              break;

            case 'stage3_start':
              updateConversationById(targetConversationId, (prev) =>
                updateLastAssistantMessage(prev, (lastMsg) => {
                  if (lastMsg.loading) {
                    lastMsg.loading.stage3 = true;
                  }
                  return lastMsg;
                })
              );
              break;

            case 'stage3_complete':
              updateConversationById(targetConversationId, (prev) =>
                updateLastAssistantMessage(prev, (lastMsg) => {
                  lastMsg.stage3 = event.data;
                  if (lastMsg.loading) {
                    lastMsg.loading.stage3 = false;
                  }
                  return lastMsg;
                })
              );
              break;

            case 'title_complete':
              // Reload conversations to get updated title
              loadConversations();
              break;

            case 'complete':
              // Stream complete, reload conversations list
              loadConversations();
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
                updateLastAssistantMessage(prev, (lastMsg) => {
                  if (lastMsg?.loading) {
                    lastMsg.loading.stage1 = false;
                    lastMsg.loading.stage2 = false;
                    lastMsg.loading.stage3 = false;
                  }
                  return lastMsg;
                })
              );
              setStreamController(null);
              setStreamingConversationId(null);
              break;

            default:
              console.log('Unknown event type:', eventType);
          }
        },
        { signal: controller.signal }
      );
    } catch (error) {
      if (error.name === 'AbortError') {
        updateConversationById(targetConversationId, (prev) =>
          updateLastAssistantMessage(prev, (lastMsg) => {
            if (lastMsg?.loading) {
              lastMsg.loading.stage1 = false;
              lastMsg.loading.stage2 = false;
              lastMsg.loading.stage3 = false;
            }
            return lastMsg;
          })
        );
      } else {
        console.error('Failed to send message:', error);
        // Remove optimistic messages on error
        updateConversationById(targetConversationId, (prev) => ({
          ...prev,
          messages: prev.messages.slice(0, -2),
        }));
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
        <ChatInterface
          conversation={currentConversation}
          onSendMessage={handleSendMessage}
          onStop={handleStop}
          onRetry={handleRetry}
          isLoading={streamingConversationId === currentConversationId}
          remainingMessages={remainingMessages}
        />
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

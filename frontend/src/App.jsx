import { useState, useEffect, useRef } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import { api } from './api';
import './App.css';

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [streamController, setStreamController] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);
  const [undoSecondsLeft, setUndoSecondsLeft] = useState(0);
  const deleteTimerRef = useRef(null);
  const deleteIntervalRef = useRef(null);

  // Load conversations on mount
  useEffect(() => {
    loadConversations();
  }, []);

  // Load conversation details when selected
  useEffect(() => {
    if (currentConversationId) {
      loadConversation(currentConversationId);
    }
  }, [currentConversationId]);

  const loadConversations = async () => {
    try {
      const convs = await api.listConversations();
      setConversations(convs);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  };

  const loadConversation = async (id) => {
    try {
      const conv = await api.getConversation(id);
      setCurrentConversation(conv);
    } catch (error) {
      console.error('Failed to load conversation:', error);
    }
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
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = (id) => {
    setCurrentConversationId(id);
  };

  const handleSendMessage = async (content) => {
    if (!currentConversationId) return;

    setIsLoading(true);
    const controller = new AbortController();
    setStreamController(controller);
    try {
      // Optimistically add user message to UI
      const userMessage = { role: 'user', content };
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, userMessage],
      }));

      // Create a partial assistant message that will be updated progressively
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

      // Add the partial assistant message
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, assistantMessage],
      }));

      // Send message with streaming
      await api.sendMessageStream(
        currentConversationId,
        content,
        (eventType, event) => {
        switch (eventType) {
          case 'stage1_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage1 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage1_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage1 = event.data;
              lastMsg.loading.stage1 = false;
              return { ...prev, messages };
            });
            break;

          case 'stage2_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage2 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage2_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage2 = event.data;
              lastMsg.metadata = event.metadata;
              lastMsg.loading.stage2 = false;
              return { ...prev, messages };
            });
            break;

          case 'stage3_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage3 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage3_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage3 = event.data;
              lastMsg.loading.stage3 = false;
              return { ...prev, messages };
            });
            break;

          case 'title_complete':
            // Reload conversations to get updated title
            loadConversations();
            break;

          case 'complete':
            // Stream complete, reload conversations list
            loadConversations();
            setIsLoading(false);
            setStreamController(null);
            break;

          case 'error':
            console.error('Stream error:', event.message);
            setIsLoading(false);
            setStreamController(null);
            break;
          case 'cancelled':
            setCurrentConversation((prev) => {
              if (!prev?.messages?.length) return prev;
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              if (lastMsg?.loading) {
                lastMsg.loading.stage1 = false;
                lastMsg.loading.stage2 = false;
                lastMsg.loading.stage3 = false;
              }
              return { ...prev, messages };
            });
            setIsLoading(false);
            setStreamController(null);
            break;

          default:
            console.log('Unknown event type:', eventType);
        }
        },
        { signal: controller.signal }
      );
    } catch (error) {
      if (error.name === 'AbortError') {
        setCurrentConversation((prev) => {
          if (!prev?.messages?.length) return prev;
          const messages = [...prev.messages];
          const lastMsg = messages[messages.length - 1];
          if (lastMsg?.loading) {
            lastMsg.loading.stage1 = false;
            lastMsg.loading.stage2 = false;
            lastMsg.loading.stage3 = false;
          }
          return { ...prev, messages };
        });
      } else {
        console.error('Failed to send message:', error);
        // Remove optimistic messages on error
        setCurrentConversation((prev) => ({
          ...prev,
          messages: prev.messages.slice(0, -2),
        }));
      }
      setIsLoading(false);
      setStreamController(null);
    }
  };

  const handleStop = () => {
    if (streamController) {
      streamController.abort();
    }
    if (currentConversationId) {
      api.cancelMessageStream(currentConversationId).catch((error) => {
        console.error('Failed to cancel stream:', error);
      });
    }
  };

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        onDeleteConversation={handleDeleteConversation}
      />
      <ChatInterface
        conversation={currentConversation}
        onSendMessage={handleSendMessage}
        onStop={handleStop}
        isLoading={isLoading}
      />
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

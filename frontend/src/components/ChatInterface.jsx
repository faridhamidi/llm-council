import { useState, useEffect, useRef, useMemo, useLayoutEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import StageResponses from './StageResponses';
import StageRankings from './StageRankings';
import StageSynthesis from './StageSynthesis';
import './ChatInterface.css';

const MARKDOWN_PLUGINS = [remarkGfm];
const INITIAL_RENDERED_MESSAGES = 40;
const LOAD_OLDER_BATCH = 40;

function CopyButton({ text, label = 'Copy', copiedLabel = 'Copied', className }) {
  const [copied, setCopied] = useState(false);
  const hasText = Boolean(text);

  const handleCopy = async () => {
    if (!hasText) return;
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.setAttribute('readonly', '');
        textarea.style.position = 'absolute';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error('Failed to copy message:', error);
    }
  };

  return (
    <button
      className={className}
      onClick={handleCopy}
      disabled={!hasText}
    >
      {copied ? copiedLabel : label}
    </button>
  );
}

export default function ChatInterface({
  conversation,
  onSendMessage,
  onStop,
  isLoading,
  onRetry,
  onResume,
  remainingMessages,
}) {
  const [input, setInput] = useState('');
  const [visibleStart, setVisibleStart] = useState(0);
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);
  const messagesContainerRef = useRef(null);
  const messagesEndRef = useRef(null);
  const shouldAutoScrollRef = useRef(true);
  const prependScrollAdjustmentRef = useRef(null);
  const textareaRef = useRef(null);
  const composerRef = useRef(null);
  const [composerHeight, setComposerHeight] = useState(170);
  const AUTO_SCROLL_BOTTOM_THRESHOLD = 80;

  // Check for paused state
  const lastMessage = conversation?.messages?.[conversation.messages.length - 1];
  const isPaused =
    lastMessage?.role === 'assistant' &&
    lastMessage?.metadata?.execution_state === 'paused';

  const handleResumeSubmit = (e) => {
    e.preventDefault();
    if (input.trim() && !isLoading && onResume) {
      onResume(input);
      setInput('');
    }
  };

  const buildLabelMap = useCallback((stages) => {
    if (!Array.isArray(stages)) return null;
    for (const stage of stages) {
      if (stage?.label_to_model) {
        return stage.label_to_model;
      }
    }
    return null;
  }, []);

  const renderDynamicStages = useCallback((message) => {
    const stages = message?.stages;
    if (!Array.isArray(stages) || stages.length === 0) {
      return null;
    }
    const labelMap = buildLabelMap(stages);
    return stages.map((stage, stageIndex) => {
      const stageLabelMap = stage.label_to_model || labelMap;
      const hasResults = stage.kind === 'synthesis'
        ? Boolean(stage.results && typeof stage.results === 'object' && stage.results.response)
        : Array.isArray(stage.results) && stage.results.length > 0;
      if (stage.status === 'running' && !hasResults) {
        return (
          <div key={stage.id || stageIndex} className="stage-loading">
            <div className="spinner"></div>
            <span>Running: {stage.name || `Stage ${stageIndex + 1}`}...</span>
          </div>
        );
      }
      const stageKey = stage.id || stageIndex;
      if (stage.kind === 'rankings') {
        return (
          <div key={stageKey}>
            {stage.status === 'running' && (
              <div className="stage-loading">
                <div className="spinner"></div>
                <span>Generating: {stage.name || `Stage ${stageIndex + 1}`}...</span>
              </div>
            )}
            <StageRankings
              rankings={stage.results}
              labelToModel={stageLabelMap}
              aggregateRankings={stage.aggregate_rankings}
              stageName={stage.name}
              stagePrompt={stage.prompt}
            />
          </div>
        );
      }
      if (stage.kind === 'synthesis') {
        return (
          <div key={stageKey}>
            {stage.status === 'running' && (
              <div className="stage-loading">
                <div className="spinner"></div>
                <span>Generating: {stage.name || `Stage ${stageIndex + 1}`}...</span>
              </div>
            )}
            <StageSynthesis
              finalResponse={stage.results}
              labelToModel={stageLabelMap}
              stageName={stage.name}
              stagePrompt={stage.prompt}
            />
          </div>
        );
      }
      return (
        <div key={stageKey}>
          {stage.status === 'running' && (
            <div className="stage-loading">
              <div className="spinner"></div>
              <span>Generating: {stage.name || `Stage ${stageIndex + 1}`}...</span>
            </div>
          )}
          <StageResponses
            responses={stage.results}
            stageName={stage.name}
            stagePrompt={stage.prompt}
          />
        </div>
      );
    });
  }, [buildLabelMap]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const isNearBottom = () => {
    const container = messagesContainerRef.current;
    if (!container) return true;
    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    return distanceFromBottom <= AUTO_SCROLL_BOTTOM_THRESHOLD;
  };

  const handleMessagesScroll = () => {
    const nearBottom = isNearBottom();
    shouldAutoScrollRef.current = nearBottom;
    setShowJumpToLatest(!nearBottom);
  };

  const handleJumpToLatest = () => {
    shouldAutoScrollRef.current = true;
    setShowJumpToLatest(false);
    scrollToBottom();
  };

  const handleShowOlderMessages = () => {
    if (visibleStart <= 0) return;
    const container = messagesContainerRef.current;
    if (container) {
      prependScrollAdjustmentRef.current = {
        scrollHeight: container.scrollHeight,
        scrollTop: container.scrollTop,
      };
    }
    setVisibleStart((prev) => Math.max(0, prev - LOAD_OLDER_BATCH));
  };

  const resizeComposerTextarea = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    const maxHeight = 400;
    const nextHeight = Math.min(el.scrollHeight, maxHeight);
    el.style.height = `${nextHeight}px`;
    el.style.overflowY = el.scrollHeight > maxHeight ? 'auto' : 'hidden';
  };

  useEffect(() => {
    if (shouldAutoScrollRef.current) {
      scrollToBottom();
      setShowJumpToLatest(false);
    } else {
      setShowJumpToLatest(true);
    }
  }, [conversation]);

  useEffect(() => {
    shouldAutoScrollRef.current = true;
    setShowJumpToLatest(false);
    const total = conversation?.messages?.length || 0;
    setVisibleStart(Math.max(0, total - INITIAL_RENDERED_MESSAGES));
    prependScrollAdjustmentRef.current = null;
  }, [conversation?.id]);

  useEffect(() => {
    const total = conversation?.messages?.length || 0;
    if (visibleStart > total) {
      setVisibleStart(Math.max(0, total - INITIAL_RENDERED_MESSAGES));
    }
  }, [conversation?.messages?.length, visibleStart]);

  useLayoutEffect(() => {
    const adjustment = prependScrollAdjustmentRef.current;
    if (!adjustment) return;
    const container = messagesContainerRef.current;
    if (!container) {
      prependScrollAdjustmentRef.current = null;
      return;
    }
    const heightDelta = container.scrollHeight - adjustment.scrollHeight;
    container.scrollTop = adjustment.scrollTop + heightDelta;
    prependScrollAdjustmentRef.current = null;
  }, [visibleStart, conversation?.messages?.length]);

  useEffect(() => {
    resizeComposerTextarea();
  }, [input, isPaused, conversation?.messages?.length, remainingMessages]);

  useEffect(() => {
    const composer = composerRef.current;
    if (!composer) {
      setComposerHeight(24);
      return;
    }

    const updateHeight = () => {
      const rect = composer.getBoundingClientRect();
      setComposerHeight(Math.max(120, Math.ceil(rect.height)));
    };

    updateHeight();

    if (typeof ResizeObserver === 'undefined') {
      return undefined;
    }

    const observer = new ResizeObserver(() => {
      updateHeight();
    });
    observer.observe(composer);
    return () => observer.disconnect();
  }, [isPaused, remainingMessages, conversation?.messages?.length]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (input.trim() && !isLoading) {
      onSendMessage(input);
      setInput('');
    }
  };

  const handleKeyDown = (e) => {
    // Submit on Enter (without Shift)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  // Calculate message counter display
  const totalMessages = conversation?.messages?.length || 0;
  const hasMessages = totalMessages > 0;
  const hasOlderMessages = hasMessages && visibleStart > 0;
  const conversationMode = conversation?.mode || 'council';
  const isChatMode = conversationMode === 'chat';
  const visibleMessages = useMemo(() => {
    if (!hasMessages) return [];
    return conversation.messages.slice(visibleStart);
  }, [hasMessages, conversation?.messages, visibleStart]);
  const renderMessage = useCallback((msg, index) => {
    if (msg.role === 'user') {
      return (
        <div key={index} className="message-group">
          <div className="user-message">
            <div className="message-header">
              <div className="message-label">You</div>
              <CopyButton text={msg.content} className="copy-message-btn" />
            </div>
            <div className="message-content">
              <div className="markdown-content">
                <ReactMarkdown remarkPlugins={MARKDOWN_PLUGINS}>
                  {msg.content}
                </ReactMarkdown>
              </div>
            </div>
          </div>
        </div>
      );
    }

    if (msg.message_type === 'speaker') {
      const speakerResponse = msg.speaker_response || msg.response;
      const speakerModel = msg.speaker_model || msg.model || (conversationMode === 'chat' ? 'Assistant' : 'Council Speaker');
      const hasError = msg.error;

      return (
        <div key={index} className="message-group">
          <div className="speaker-message">
            <div className="message-header">
              <div className="message-label speaker-label">
                💬 {speakerModel}
              </div>
              <CopyButton text={speakerResponse} className="copy-message-btn" />
              {hasError && onRetry && (
                <button className="retry-btn" onClick={() => onRetry && onRetry()}>
                  Retry
                </button>
              )}
            </div>
            <div className="message-content">
              <div className="markdown-content">
                <ReactMarkdown remarkPlugins={MARKDOWN_PLUGINS}>
                  {speakerResponse}
                </ReactMarkdown>
              </div>
            </div>
          </div>
        </div>
      );
    }

    return (
      <div key={index} className="message-group">
        <div className="assistant-message">
          <div className="message-label">🏛️ LLM Council</div>
          {renderDynamicStages(msg)}
        </div>
      </div>
    );
  }, [conversationMode, onRetry, renderDynamicStages]);
  const renderedMessages = useMemo(() => {
    if (!visibleMessages.length) return null;
    return visibleMessages.map((msg, offset) => renderMessage(msg, visibleStart + offset));
  }, [visibleMessages, renderMessage, visibleStart]);
  const messageCounter = remainingMessages !== undefined && remainingMessages !== null && hasMessages ? (
    <div className={`message-counter ${remainingMessages <= 5 ? 'warning' : ''} ${remainingMessages === 0 ? 'limit-reached' : ''}`}>
      {remainingMessages === 0
        ? (isChatMode
          ? "Chat message limit reached. Start a new chat."
          : "Message limit reached. Start a new conversation.")
        : (isChatMode
          ? `${remainingMessages} message${remainingMessages !== 1 ? 's' : ''} remaining`
          : `${remainingMessages} follow-up${remainingMessages !== 1 ? 's' : ''} remaining`)}
    </div>
  ) : null;

  if (!conversation) {
    return (
      <div className="chat-interface">
        <div className="empty-state">
          <h2>Welcome to LLM Council</h2>
          <p>Create a new conversation to get started</p>
        </div>
      </div>
    );
  }

  return (
    <div
      className="chat-interface"
      style={{ '--composer-height': `${composerHeight}px` }}
    >
      <div
        ref={messagesContainerRef}
        className="messages-container"
        onScroll={handleMessagesScroll}
      >
        {conversation.messages.length === 0 ? (
          <div className="empty-state">
            <h2>Start a conversation</h2>
            <p>{isChatMode ? 'Start chatting with a single model' : 'Ask a question to consult the LLM Council'}</p>
          </div>
        ) : (
          <>
            {hasOlderMessages && (
              <div className="load-older-container">
                <button
                  type="button"
                  className="load-older-btn"
                  onClick={handleShowOlderMessages}
                >
                  Show {Math.min(LOAD_OLDER_BATCH, visibleStart)} older message{Math.min(LOAD_OLDER_BATCH, visibleStart) === 1 ? '' : 's'}
                </button>
              </div>
            )}
            {renderedMessages}
          </>
        )}

        {isLoading && (
          <div className="loading-indicator">
            <div className="spinner"></div>
            <span>{isChatMode ? 'Thinking...' : 'Consulting the council...'}</span>
            {onStop && (
              <button className="stop-button" onClick={onStop}>
                Stop
              </button>
            )}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {showJumpToLatest && (
        <button
          type="button"
          className="jump-to-latest-btn"
          onClick={handleJumpToLatest}
          aria-label="Jump to latest message"
        >
          Jump to latest
        </button>
      )}

      {isPaused && (
        <div className="paused-input-container" ref={composerRef}>
          <div className="paused-banner">
            <span className="paused-icon">⏸️</span>
            <span>Council Paused - Waiting for Human Input</span>
          </div>
          <form className="input-form paused-form" onSubmit={handleResumeSubmit}>
            <div className="composer-surface">
              <textarea
                ref={textareaRef}
                className="message-input"
                placeholder="Provide your input to resume the council..."
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleResumeSubmit(e);
                  }
                }}
                disabled={isLoading}
                rows={3}
                autoFocus
              />
              <button
                type="submit"
                className="send-button resume-button"
                disabled={!input.trim() || isLoading}
              >
                Resume Council
              </button>
            </div>
          </form>
        </div>
      )}

      {hasMessages && remainingMessages !== 0 && !isPaused && (
        <form className="input-form follow-up" onSubmit={handleSubmit} ref={composerRef}>
          {messageCounter}
          <div className="composer-surface">
            <div className="input-wrapper">
              <textarea
                ref={textareaRef}
                className="message-input"
                placeholder={isChatMode ? "Send a message..." : "Ask a follow-up question..."}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isLoading || remainingMessages === 0}
                rows={1}
              />
            </div>
            {isChatMode ? (
              <div className="input-actions">
                <button
                  type="submit"
                  className="send-button"
                  disabled={!input.trim() || isLoading || remainingMessages === 0}
                >
                  Send
                </button>
              </div>
            ) : (
              <div className="input-actions">
                <button
                  type="button"
                  className="reconvene-button"
                  title="Force the full council to reconvene and deliberate on this question."
                  disabled={!input.trim() || isLoading || remainingMessages === 0}
                  onClick={() => {
                    if (input.trim() && !isLoading) {
                      onSendMessage(input, true); // Force Council
                      setInput('');
                    }
                  }}
                >
                  Ask Council
                </button>
                <button
                  type="submit"
                  className="send-button"
                  disabled={!input.trim() || isLoading || remainingMessages === 0}
                  title="Ask the Council Speaker (faster)"
                >
                  Ask Speaker
                </button>
              </div>
            )}
          </div>
        </form>
      )}

      {conversation.messages.length === 0 && (
        <form className="input-form" onSubmit={handleSubmit} ref={composerRef}>
          <div className="composer-surface">
            <textarea
              ref={textareaRef}
              className="message-input"
              placeholder={isChatMode
                ? "Send a message... (Shift+Enter for new line, Enter to send)"
                : "Ask your question... (Shift+Enter for new line, Enter to send)"}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isLoading}
              rows={1}
            />
            <button
              type="submit"
              className="send-button"
              disabled={!input.trim() || isLoading}
            >
              Send
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

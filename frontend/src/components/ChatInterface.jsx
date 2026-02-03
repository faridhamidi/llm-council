import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import StageResponses from './StageResponses';
import StageRankings from './StageRankings';
import StageSynthesis from './StageSynthesis';
import './ChatInterface.css';

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
  const messagesEndRef = useRef(null);

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

  const buildLabelMap = (stages) => {
    if (!Array.isArray(stages)) return null;
    for (const stage of stages) {
      if (stage?.label_to_model) {
        return stage.label_to_model;
      }
    }
    return null;
  };

  const renderDynamicStages = (message) => {
    const stages = message?.stages;
    if (!Array.isArray(stages) || stages.length === 0) {
      return null;
    }
    const labelMap = buildLabelMap(stages);
    return stages.map((stage, stageIndex) => {
      const stageLabelMap = stage.label_to_model || labelMap;
      if (stage.status === 'running') {
        return (
          <div key={stage.id || stageIndex} className="stage-loading">
            <div className="spinner"></div>
            <span>Running: {stage.name || `Stage ${stageIndex + 1}`}...</span>
          </div>
        );
      }
      if (stage.kind === 'rankings') {
        return (
          <StageRankings
            key={stage.id || stageIndex}
            rankings={stage.results}
            labelToModel={stageLabelMap}
            aggregateRankings={stage.aggregate_rankings}
            stageName={stage.name}
            stagePrompt={stage.prompt}
          />
        );
      }
      if (stage.kind === 'synthesis') {
        return (
          <StageSynthesis
            key={stage.id || stageIndex}
            finalResponse={stage.results}
            labelToModel={stageLabelMap}
            stageName={stage.name}
            stagePrompt={stage.prompt}
          />
        );
      }
      return (
        <StageResponses
          key={stage.id || stageIndex}
          responses={stage.results}
          stageName={stage.name}
          stagePrompt={stage.prompt}
        />
      );
    });
  };

  const renderSpeakerMessage = (msg) => {
    const speakerResponse = msg.speaker_response || msg.response;
    const speakerModel = msg.speaker_model || msg.model || 'Council Speaker';
    const hasError = msg.error;

    return (
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
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {speakerResponse}
            </ReactMarkdown>
          </div>
        </div>
      </div>
    );
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [conversation]);

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
  const hasMessages = conversation?.messages?.length > 0;
  const messageCounter = remainingMessages !== undefined && remainingMessages !== null && hasMessages ? (
    <div className={`message-counter ${remainingMessages <= 5 ? 'warning' : ''} ${remainingMessages === 0 ? 'limit-reached' : ''}`}>
      {remainingMessages === 0
        ? "Message limit reached. Start a new conversation."
        : `${remainingMessages} follow-up${remainingMessages !== 1 ? 's' : ''} remaining`}
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
    <div className="chat-interface">
      <div className="messages-container">
        {conversation.messages.length === 0 ? (
          <div className="empty-state">
            <h2>Start a conversation</h2>
            <p>Ask a question to consult the LLM Council</p>
          </div>
        ) : (
          conversation.messages.map((msg, index) => (
            <div key={index} className="message-group">
              {msg.role === 'user' ? (
                <div className="user-message">
                  <div className="message-header">
                    <div className="message-label">You</div>
                    <CopyButton text={msg.content} className="copy-message-btn" />
                  </div>
                  <div className="message-content">
                    <div className="markdown-content">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {msg.content}
                      </ReactMarkdown>
                    </div>
                  </div>
                </div>
              ) : msg.message_type === 'speaker' ? (
                renderSpeakerMessage(msg)
              ) : (
                <div className="assistant-message">
                  <div className="message-label">🏛️ LLM Council</div>
                  {renderDynamicStages(msg)}
                </div>
              )}
            </div>
          ))
        )}

        {isLoading && (
          <div className="loading-indicator">
            <div className="spinner"></div>
            <span>Consulting the council...</span>
            {onStop && (
              <button className="stop-button" onClick={onStop}>
                Stop
              </button>
            )}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {isPaused && (
        <div className="paused-input-container">
          <div className="paused-banner">
            <span className="paused-icon">⏸️</span>
            <span>Council Paused - Waiting for Human Input</span>
          </div>
          <form className="input-form paused-form" onSubmit={handleResumeSubmit}>
            <textarea
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
          </form>
        </div>
      )}

      {hasMessages && remainingMessages !== 0 && !isPaused && (
        <form className="input-form follow-up" onSubmit={handleSubmit}>
          {messageCounter}
          <div className="input-wrapper">
            <textarea
              className="message-input"
              placeholder="Ask a follow-up question..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isLoading || remainingMessages === 0}
              rows={2}
            />
          </div>
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
        </form>
      )}

      {conversation.messages.length === 0 && (
        <form className="input-form" onSubmit={handleSubmit}>
          <textarea
            className="message-input"
            placeholder="Ask your question... (Shift+Enter for new line, Enter to send)"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            rows={3}
          />
          <button
            type="submit"
            className="send-button"
            disabled={!input.trim() || isLoading}
          >
            Send
          </button>
        </form>
      )}
    </div>
  );
}

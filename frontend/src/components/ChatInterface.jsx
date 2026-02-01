import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';
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

  const buildLabelMap = (message) => {
    if (message?.metadata?.label_to_model) {
      return message.metadata.label_to_model;
    }
    if (!message?.stage1 || !Array.isArray(message.stage1)) return null;

    const successful = message.stage1.filter(
      (result) => result.status !== 'failed' && result.response
    );
    if (!successful.length) return null;

    const labelMap = {};
    successful.forEach((result, index) => {
      const label = `Response ${String.fromCharCode(65 + index)}`;
      labelMap[label] = result.model;
    });
    return labelMap;
  };

  const renderDynamicStages = (message) => {
    const stages = message?.stages;
    if (!Array.isArray(stages) || stages.length === 0) {
      return null;
    }
    return stages.map((stage, stageIndex) => {
      const stageLabelMap = stage.label_to_model || buildLabelMap(message);
      if (stage.kind === 'rankings') {
        return (
          <Stage2
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
          <Stage3
            key={stage.id || stageIndex}
            finalResponse={stage.results}
            labelToModel={stageLabelMap}
            stageName={stage.name}
            stagePrompt={stage.prompt}
          />
        );
      }
      return (
        <Stage1
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
  const messageCounter = remainingMessages !== undefined && hasMessages ? (
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
                  {(() => {
                    const labelToModel = buildLabelMap(msg);
                    const dynamicStages = renderDynamicStages(msg);
                    return (
                      <>
                        {dynamicStages}
                        {!dynamicStages && (
                          <>
                            {/* Stage 1 */}
                            {msg.loading?.stage1 && (
                              <div className="stage-loading">
                                <div className="spinner"></div>
                                <span>Running: Collecting individual responses...</span>
                              </div>
                            )}
                            {msg.stage1 && <Stage1 responses={msg.stage1} />}

                            {/* Stage 2 */}
                            {msg.loading?.stage2 && (
                              <div className="stage-loading">
                                <div className="spinner"></div>
                                <span>Running: Peer rankings...</span>
                              </div>
                            )}
                            {msg.stage2 && (
                              <Stage2
                                rankings={msg.stage2}
                                labelToModel={labelToModel}
                                aggregateRankings={msg.metadata?.aggregate_rankings}
                              />
                            )}

                            {/* Stage 3 */}
                            {msg.loading?.stage3 && (
                              <div className="stage-loading">
                                <div className="spinner"></div>
                                <span>Running: Final synthesis...</span>
                              </div>
                            )}
                            {msg.stage3 && (
                              <Stage3
                                finalResponse={msg.stage3}
                                labelToModel={labelToModel}
                              />
                            )}
                          </>
                        )}
                      </>
                    );
                  })()}
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
          <textarea
            className="message-input"
            placeholder="Ask a follow-up question..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading || remainingMessages === 0}
            rows={2}
          />
          <button
            type="submit"
            className="send-button"
            disabled={!input.trim() || isLoading || remainingMessages === 0}
          >
            Send
          </button>
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

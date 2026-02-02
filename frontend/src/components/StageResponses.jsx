import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './StageResponses.css';

export default function StageResponses({ responses, stageName = 'Individual Responses', stagePrompt = '' }) {
  const [activeTab, setActiveTab] = useState(0);
  const [copied, setCopied] = useState(false);

  if (!responses || responses.length === 0) {
    return null;
  }

  const activeResponse = responses[activeTab];

  const buildCopyText = () => {
    if (!activeResponse) return '';
    const header = `Model: ${activeResponse.model}`;
    if (activeResponse.status === 'failed') {
      const errorLine = activeResponse.error ? `\nError: ${activeResponse.error}` : '';
      return `${header}\nStatus: failed${errorLine}`;
    }
    const promptWarning = activeResponse.system_prompt_dropped
      ? '\nSystem prompt ignored by this model.'
      : '';
    return `${header}${promptWarning}\n\n${activeResponse.response || ''}`;
  };

  const handleCopy = async () => {
    const text = buildCopyText();
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
      console.error('Failed to copy Stage 1 output:', error);
    }
  };

  return (
    <div className="stage stage-responses">
      <h3 className="stage-title">{stageName}</h3>
      {stagePrompt && <div className="stage-prompt-text">{stagePrompt}</div>}

      <div className="tabs">
        {responses.map((resp, index) => (
          <button
            key={index}
            className={`tab ${activeTab === index ? 'active' : ''} ${resp.status === 'failed' ? 'failed' : ''}`}
            onClick={() => {
              setActiveTab(index);
              setCopied(false);
            }}
          >
            {resp.model}{resp.status === 'failed' ? ' (failed)' : ''}
          </button>
        ))}
      </div>

      <div className="tab-content">
        <div className="tab-content-header">
          <div className="model-name">{activeResponse.model}</div>
          <button className="copy-stage-btn" onClick={handleCopy}>
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
        {activeResponse.system_prompt_dropped && (
          <div className="system-prompt-warning">
            System prompt ignored by this model (continued without it).
          </div>
        )}
        {activeResponse.status === 'failed' ? (
          <div className="response-text markdown-content">
            <p><strong>Failed to respond.</strong></p>
            {activeResponse.error && <p>{activeResponse.error}</p>}
          </div>
        ) : (
          <div className="response-text markdown-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {activeResponse.response}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}

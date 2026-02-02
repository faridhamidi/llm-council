import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './StageSynthesis.css';

function deAnonymizeText(text, labelToModel) {
  if (!labelToModel) return text;
  let result = text;
  Object.entries(labelToModel).forEach(([label, model]) => {
    result = result.replace(new RegExp(label, 'g'), `**${model}**`);
  });
  return result;
}

export default function StageSynthesis({
  finalResponse,
  labelToModel,
  stageName = 'Final Council Answer',
  stagePrompt = '',
}) {
  const [copied, setCopied] = useState(false);

  if (!finalResponse) {
    return null;
  }

  const handleCopy = async () => {
    const raw = finalResponse.response || '';
    const text = `Chairman: ${finalResponse.model}\n\n${deAnonymizeText(raw, labelToModel)}`;
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
      console.error('Failed to copy Stage 3 output:', error);
    }
  };

  return (
    <div className="stage stage-synthesis">
      <h3 className="stage-title">{stageName}</h3>
      {stagePrompt && <div className="stage-prompt-text">{stagePrompt}</div>}
      <div className="final-response">
        <div className="stage-synthesis-header">
          <div className="chairman-label">Chairman: {finalResponse.model}</div>
          <button className="copy-stage-synthesis-btn" onClick={handleCopy}>
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
        <div className="final-text markdown-content">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {deAnonymizeText(finalResponse.response, labelToModel)}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
}

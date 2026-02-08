import { useState } from 'react';
import { useCouncilStudio } from '../../hooks/useCouncilStudio.js';
import PresetControls from './PresetControls.jsx';
import StepRoles from './StepRoles.jsx';
import StepStages from './StepStages.jsx';
import StepOverview from './StepOverview.jsx';
import { STEP_ITEMS } from './constants.js';
import './CouncilStudio.css';

export default function CouncilStudio({ onClose }) {
  const [step, setStep] = useState(1);

  const {
    loading,
    saving,
    error,
    warning,
    status,
    models,
    draft,
    selectedMemberId,
    selectedStageId,
    presets,
    selectedPresetId,
    presetNameInput,
    presetStatus,
    validation,
    selectedMember,
    selectedStage,
    setSelectedMemberId,
    setSelectedStageId,
    setSelectedPresetId,
    setPresetNameInput,
    updateMember,
    addMember,
    removeMember,
    addStage,
    updateStage,
    removeStage,
    moveStage,
    toggleMemberInStage,
    handleSave,
    handleSavePreset,
    handleApplyPreset,
    handleDeletePreset,
    handleExportStored,
  } = useCouncilStudio();

  if (loading) {
    return (
      <div className="studio-page">
        <div className="studio-loading">Loading council studio...</div>
      </div>
    );
  }

  if (!draft) {
    return (
      <div className="studio-page">
        <div className="studio-error">{error || 'Failed to load studio.'}</div>
      </div>
    );
  }

  return (
    <div className="studio-page">
      <div className="studio-shell">
        <div className="studio-header">
          <div>
            <h1>Council Studio</h1>
            <p>Configure your LLM Council pipeline with roles, stages, and execution flow.</p>
          </div>
          <div className="studio-actions">
            <button className="studio-btn" onClick={handleExportStored}>Export Stored JSON</button>
            <button className="studio-btn primary" onClick={handleSave} disabled={saving}>
              {saving ? 'Saving...' : 'Save Settings'}
            </button>
            <button className="studio-btn" onClick={onClose}>Close</button>
          </div>
        </div>

        <div className="studio-stepper">
          {STEP_ITEMS.map((item, index) => (
            <div key={item.id} className="step-wrap">
              <button
                className={`step-node ${step === item.id ? 'active' : ''} ${step > item.id ? 'completed' : ''}`}
                onClick={() => setStep(item.id)}
              >
                <div className="step-number">{item.id}</div>
                <div className="step-label">{item.label}</div>
              </button>
              {index < STEP_ITEMS.length - 1 && <div className="step-divider" />}
            </div>
          ))}
        </div>

        {status && <div className="studio-status success">{status}</div>}
        {warning && <div className="studio-status warn">{warning}</div>}
        {error && <div className="studio-status error">{error}</div>}
        {presetStatus && (
          <div className={`studio-status ${presetStatus.type}`}>{presetStatus.message}</div>
        )}

        <PresetControls
          presets={presets}
          selectedPresetId={selectedPresetId}
          presetNameInput={presetNameInput}
          onSelectedPresetChange={setSelectedPresetId}
          onPresetNameChange={setPresetNameInput}
          onSave={handleSavePreset}
          onApply={handleApplyPreset}
          onDelete={handleDeletePreset}
        />

        {step === 1 && (
          <StepRoles
            members={draft.members}
            models={models}
            selectedMemberId={selectedMemberId}
            selectedMember={selectedMember}
            onSelectMember={setSelectedMemberId}
            onAddMember={addMember}
            onUpdateMember={updateMember}
            onRemoveMember={removeMember}
          />
        )}

        {step === 2 && (
          <StepStages
            stages={draft.stages}
            members={draft.members}
            selectedStageId={selectedStageId}
            selectedStage={selectedStage}
            onSelectStage={setSelectedStageId}
            onAddStage={addStage}
            onUpdateStage={updateStage}
            onRemoveStage={removeStage}
            onMoveStage={moveStage}
            onToggleMember={toggleMemberInStage}
          />
        )}

        {step === 3 && (
          <StepOverview
            draft={draft}
            validation={validation}
          />
        )}

        <div className="studio-footer-nav">
          <button className="studio-btn" onClick={() => setStep((prev) => Math.max(1, prev - 1))} disabled={step === 1}>Back</button>
          <button className="studio-btn" onClick={() => setStep((prev) => Math.min(3, prev + 1))} disabled={step === 3}>Next</button>
        </div>
      </div>
    </div>
  );
}

/**
 * PresetControls - Manage council configuration presets
 */

export default function PresetControls({
    presets,
    selectedPresetId,
    presetNameInput,
    onSelectedPresetChange,
    onPresetNameChange,
    onSave,
    onApply,
    onDelete,
}) {
    return (
        <div className="studio-presets">
            <div className="preset-row">
                <label htmlFor="council-preset-name">Save Preset</label>
                <div className="preset-controls">
                    <input
                        id="council-preset-name"
                        type="text"
                        placeholder="Enter preset name"
                        value={presetNameInput}
                        onChange={(e) => onPresetNameChange(e.target.value)}
                    />
                    <button className="studio-btn" onClick={onSave}>Save</button>
                </div>
            </div>
            <div className="preset-row">
                <label htmlFor="council-preset-select">Apply Preset</label>
                <div className="preset-controls">
                    <select
                        id="council-preset-select"
                        value={selectedPresetId}
                        onChange={(e) => onSelectedPresetChange(e.target.value)}
                    >
                        <option value="">Select preset</option>
                        {presets.map((preset) => (
                            <option key={preset.id} value={preset.id}>{preset.name}</option>
                        ))}
                    </select>
                    <button className="studio-btn" onClick={onApply}>Apply</button>
                    <button className="studio-btn danger" onClick={onDelete}>Delete</button>
                </div>
            </div>
        </div>
    );
}

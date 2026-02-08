/* Council Studio prototype (no backend integration).
 * Goal: externalize the pipeline mental model via:
 * - Flow graph (shape)
 * - Membership matrix (who participates where)
 * - Inspector + prompt preview (what each role sees)
 * - Lint panel (static checks)
 */

const DEFAULT_STATE = () => ({
  question: "Design a UI for an LLM council that reduces cognitive load for power users.",
  members: [
    { id: "m1", alias: "Systems Analyst", model_id: "anthropic.claude-sonnet" },
    { id: "m2", alias: "Product Strategist", model_id: "meta.llama-maverick" },
    { id: "m3", alias: "Risk Auditor", model_id: "deepseek.r1" },
    { id: "m4", alias: "Chairman / Speaker", model_id: "anthropic.claude-opus" },
  ],
  stages: [
    {
      id: "s1",
      name: "Individual Responses",
      kind: "responses",
      type: "ai",
      execution_mode: "parallel",
      prompt:
        "User Question: {question}\n\nRespond with your best answer. Keep it structured.",
      member_ids: ["m1", "m2", "m3"],
    },
    {
      id: "s2",
      name: "Peer Rankings",
      kind: "rankings",
      type: "ai",
      execution_mode: "parallel",
      prompt:
        "Question: {question}\n\nHere are anonymized responses:\n\n{responses}\n\nRank them best to worst. Output a numbered list only.",
      member_ids: ["m1", "m2", "m3"],
    },
    {
      id: "s3",
      name: "Final Synthesis",
      kind: "synthesis",
      type: "ai",
      execution_mode: "sequential",
      prompt:
        "Original Question: {question}\n\nINDIVIDUAL RESPONSES:\n{stage1}\n\nPEER RANKINGS:\n{stage2}\n\nSynthesize a final answer.",
      member_ids: ["m4"],
    },
  ],
  selectedStageId: "s2",
  selectedMemberId: "m1",
  speaker_context_level: "full",
});

let state = DEFAULT_STATE();
const MAX_STAGES = 7;
const MAX_MEMBERS_PER_STAGE = 6;
const STEPS = ["roles", "stages", "overview"];
let currentStep = "roles";
let overlayMode = null;

function getFinalStage() {
  return state.stages[state.stages.length - 1];
}

function getSynthesisRoleId() {
  const last = getFinalStage();
  return last?.member_ids?.[0] || null;
}

function getSynthesisRole() {
  const id = getSynthesisRoleId();
  return state.members.find((m) => m.id === id) || null;
}

function ensureFinalStage() {
  if (state.stages.length === 0) {
    state.stages.push({
      id: `s${Date.now()}`,
      name: "Final Synthesis",
      kind: "synthesis",
      type: "ai",
      execution_mode: "sequential",
      prompt:
        "Original Question: {question}\n\nINDIVIDUAL RESPONSES:\n{stage1}\n\nPEER RANKINGS:\n{stage2}\n\nSynthesize a final answer.",
      member_ids: [],
    });
  }

  const last = getFinalStage();
  if (last.kind !== "synthesis") {
    state.stages.push({
      id: `s${Date.now()}`,
      name: "Final Synthesis",
      kind: "synthesis",
      type: "ai",
      execution_mode: "sequential",
      prompt:
        "Original Question: {question}\n\nINDIVIDUAL RESPONSES:\n{stage1}\n\nPEER RANKINGS:\n{stage2}\n\nSynthesize a final answer.",
      member_ids: [],
    });
  }

  const finalStage = getFinalStage();
  finalStage.kind = "synthesis";
  finalStage.type = "ai";
  finalStage.execution_mode = "sequential";
  finalStage.name = "Final Synthesis";

  // Prevent non-final stages from being synthesis.
  for (let i = 0; i < state.stages.length - 1; i++) {
    if (state.stages[i].kind === "synthesis") {
      state.stages[i].kind = "responses";
    }
  }

  if (!finalStage.member_ids || finalStage.member_ids.length === 0) {
    const fallback = state.members[0]?.id;
    finalStage.member_ids = fallback ? [fallback] : [];
  } else if (finalStage.member_ids.length > 1) {
    finalStage.member_ids = [finalStage.member_ids[0]];
  }
}

const $ = (sel) => document.querySelector(sel);
const stageListEl = $("#stageList");
const matrixEl = $("#matrix");
const lintListEl = $("#lintList");
const inspectorStageEl = $("#inspectorStage");
const inspectorMemberEl = $("#inspectorMember");
const diffBoxEl = $("#diffBox");
const previewBoxEl = $("#previewBox");
const previewControlsEl = $("#previewControls");
const panelLeftEl = $("#panelLeft");
const panelCenterEl = $("#panelCenter");
const panelRightEl = $("#panelRight");
const panelPreviewEl = $("#panelPreview");
const panelDiffEl = $("#panelDiff");
const toastEl = $("#toast");
const overviewViewEl = $("#overviewView");
const rolesViewEl = $("#rolesView");
const stagesViewEl = $("#stagesView");
const overviewStageTableEl = $("#overviewStageTable");
const overviewRoleListEl = $("#overviewRoleList");
const rolesListEl = $("#rolesList");
const stageOverviewGridEl = $("#stageOverviewGrid");
const lintListOverviewEl = $("#lintListOverview");
const matrixViewEl = $("#matrixView");
const centerTitleEl = $("#centerTitle");
const centerMetaEl = $("#centerMeta");
const layoutEl = document.querySelector(".layout");
const rosterBlockEl = $("#rosterBlock");
const architectEl = document.querySelector(".architect");
const backBtnEl = $("#btnBack");
const nextBtnEl = $("#btnNext");
const addRoleBtnEl = $("#btnAddRole");
const memberManagerMetaEl = $("#memberManagerMeta");
const assignedListEl = $("#assignedList");
const availableListEl = $("#availableList");
const memberSearchEl = $("#memberSearch");
const overviewStageListEl = $("#overviewStageList");
const graphSvgOverviewEl = $("#graphSvgOverview");
const pipelineGraphEl = $("#pipelineGraph");
const pipelineLintEl = $("#pipelineLint");
const addStageBtnEl = $("#btnAddStage");
const removeStageBtnEl = $("#btnRemoveStage");
const moveStageUpBtnEl = $("#btnMoveStageUp");
const moveStageDownBtnEl = $("#btnMoveStageDown");

function toast(msg) {
  toastEl.textContent = msg;
  toastEl.classList.remove("is-hidden");
  window.clearTimeout(toast._t);
  toast._t = window.setTimeout(() => toastEl.classList.add("is-hidden"), 2200);
}

function activeStage() {
  return state.stages.find((s) => s.id === state.selectedStageId) || state.stages[0];
}

function activeMember() {
  return state.members.find((m) => m.id === state.selectedMemberId) || state.members[0];
}

function stageColor(kind, type) {
  if (type === "human") return "rgba(239, 68, 68, 0.55)";
  if (kind === "responses") return "rgba(62, 207, 142, 0.55)";
  if (kind === "rankings") return "rgba(245, 158, 11, 0.55)";
  if (kind === "synthesis") return "rgba(59, 130, 246, 0.55)";
  return "rgba(255, 255, 255, 0.22)";
}

function applyTemplate(template, values) {
  let out = template || "";
  for (const [k, v] of Object.entries(values || {})) {
    out = out.split(`{${k}}`).join(String(v ?? ""));
  }
  return out;
}

function fakePriorContext() {
  const stage1 = [
    "Model A: A matrix + graph + preview reduces cognitive burden.",
    "Model B: Add lint and diff-first apply to prevent configuration mistakes.",
    "Model C: Provide a prompt simulation view to make behavior observable.",
  ].join("\n\n");
  const stage2 = ["1. Response A", "2. Response C", "3. Response B"].join("\n");
  const responses = ["Response A ...", "Response B ...", "Response C ..."].join("\n\n");
  return { stage1, stage2, responses };
}

function renderStageList(targetEl = stageListEl) {
  if (!targetEl) return;
  targetEl.innerHTML = "";
  for (const s of state.stages) {
    const isFinalStage = s.id === getFinalStage()?.id;
    const el = document.createElement("div");
    el.className = "stage-card" + (s.id === state.selectedStageId ? " is-active" : "");
    el.addEventListener("click", () => {
      state.selectedStageId = s.id;
      // Prefer selecting a member who participates, else keep selection.
      if (!s.member_ids.includes(state.selectedMemberId)) {
        state.selectedMemberId = s.member_ids[0] || state.selectedMemberId;
      }
      renderAll();
    });

    const badgeKind = `pill kind-${s.kind || "responses"}`;
    const badgeType = s.type === "human" ? "pill type-human" : "pill";
    const memberCount = (s.member_ids || []).length;
    el.innerHTML = `
      <div class="stage-line">
        <div class="stage-name">${escapeHtml(s.name)}</div>
        <div class="stage-badges">
          <span class="${badgeKind}">${escapeHtml(s.kind || "responses")}</span>
          <span class="${badgeType}">${escapeHtml(s.type || "ai")}</span>
          <span class="pill">${escapeHtml(s.execution_mode || "parallel")}</span>
          <span class="pill">${memberCount}/${MAX_MEMBERS_PER_STAGE} roles</span>
          ${isFinalStage ? '<span class="pill">Locked</span>' : ""}
        </div>
      </div>
      <div class="stage-sub">${escapeHtml(shortPrompt(s.prompt))}</div>
    `;
    targetEl.appendChild(el);
  }
  // No pipeline meta outside overview; keep list focused.
}

function shortPrompt(p) {
  const s = (p || "").trim().replace(/\s+/g, " ");
  if (!s) return "No prompt (uses fallback formatting).";
  return s.length > 94 ? s.slice(0, 92) + "…" : s;
}

function renderMatrix() {
  const cols = state.stages.length;
  matrixEl.style.setProperty("--cols", String(cols));
  matrixEl.innerHTML = "";

  // Header
  const headerRow = document.createElement("div");
  headerRow.className = "matrix-row matrix-header";
  headerRow.appendChild(cellEl("cell header", "Role"));
  for (const s of state.stages) {
    const c = cellEl("cell header stagecol" + (s.id === state.selectedStageId ? " is-active" : ""), s.name);
    c.title = `${s.kind} • ${s.execution_mode}`;
    c.style.borderTop = `2px solid ${stageColor(s.kind, s.type)}`;
    c.addEventListener("click", () => {
      state.selectedStageId = s.id;
      if (!s.member_ids.includes(state.selectedMemberId)) {
        state.selectedMemberId = s.member_ids[0] || state.selectedMemberId;
      }
      renderAll();
    });
    headerRow.appendChild(c);
  }
  matrixEl.appendChild(headerRow);

  // Body rows
  for (const m of state.members) {
    const row = document.createElement("div");
    row.className = "matrix-row";
    const memCell = document.createElement("div");
    memCell.className = "cell member";
    memCell.innerHTML = `${escapeHtml(m.alias)} <span class="muted">${escapeHtml(m.model_id)}</span>`;
    memCell.addEventListener("click", () => {
      state.selectedMemberId = m.id;
      renderAll();
    });
    row.appendChild(memCell);

    for (const s of state.stages) {
      const on = (s.member_ids || []).includes(m.id);
      const c = document.createElement("div");
      c.className = "cell stagecol" + (s.id === state.selectedStageId ? " is-active" : "");
      const t = document.createElement("button");
      t.className = "toggle" + (on ? " is-on" : "");
      t.setAttribute("aria-label", `Toggle ${m.alias} in ${s.name}`);
      t.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleMembership(s.id, m.id);
      });
      c.appendChild(t);
      c.addEventListener("click", () => {
        state.selectedStageId = s.id;
        state.selectedMemberId = m.id;
        renderAll();
      });
      row.appendChild(c);
    }
    matrixEl.appendChild(row);
  }
}

function renderRolesView() {
  if (!rolesListEl) return;
  rolesListEl.innerHTML = "";
  if (state.members.length === 0) {
    const empty = document.createElement("div");
    empty.className = "help";
    empty.textContent = "No roles defined yet. Add your first role to begin.";
    rolesListEl.appendChild(empty);
    return;
  }
  state.members.forEach((m) => {
    const el = document.createElement("div");
    el.className = "role-card" + (m.id === state.selectedMemberId ? " is-active" : "");
    el.innerHTML = `
      <div>
        <div><strong>${escapeHtml(m.alias)}</strong></div>
        <div class="role-meta">${escapeHtml(m.model_id)}</div>
      </div>
      <div class="role-actions">
        <button class="btn btn-ghost btn-small" data-action="select">Select</button>
        <button class="btn btn-ghost btn-small" data-action="remove">Remove</button>
      </div>
    `;
    el.addEventListener("click", () => {
      state.selectedMemberId = m.id;
      renderAll();
    });
    el.querySelector('[data-action="select"]').addEventListener("click", (e) => {
      e.stopPropagation();
      state.selectedMemberId = m.id;
      renderAll();
    });
    const removeBtn = el.querySelector('[data-action="remove"]');
    removeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      removeMember(m.id);
    });
    rolesListEl.appendChild(el);
  });
}

function renderStagesView() {
  const stages = state.stages.length;
  const members = state.members.length;
  const synthesisRole = getSynthesisRole() || state.members[0];
  const selected = activeStage();

  if (stageOverviewGridEl) {
    stageOverviewGridEl.innerHTML = `
      <div class="overview-card">
        <div class="label">Selected Stage</div>
        <div class="value">${escapeHtml(selected.name)}</div>
        <div class="help">${selected.member_ids.length}/${MAX_MEMBERS_PER_STAGE} roles • ${escapeHtml(selected.execution_mode)}</div>
      </div>
      <div class="overview-card">
        <div class="label">Stages</div>
        <div class="value">${stages}</div>
        <div class="help">Pipeline nodes in execution order</div>
      </div>
      <div class="overview-card">
        <div class="label">Roles</div>
        <div class="value">${members}</div>
        <div class="help">Roles are seats; models are tools</div>
      </div>
      <div class="overview-card">
      <div class="label">Synthesis Role</div>
      <div class="value">${escapeHtml(synthesisRole?.alias || "Unassigned")}</div>
      <div class="help">${escapeHtml(synthesisRole?.model_id || "Assign a role to Final Synthesis")}</div>
      </div>
      <div class="overview-card">
        <div class="label">Speaker Context</div>
        <select class="input" id="speakerContextSelect">
          ${option("minimal", state.speaker_context_level)}
          ${option("standard", state.speaker_context_level)}
          ${option("full", state.speaker_context_level)}
        </select>
      <div class="help">Follow-up context for the synthesis role</div>
      </div>
    `;
  }

  renderMemberManager();

  const select = $("#speakerContextSelect");
  if (select) {
    select.addEventListener("change", (e) => {
      state.speaker_context_level = e.target.value;
      renderDiff();
    });
  }

  updateStageActionButtons();
}

function updateStageActionButtons() {
  const finalStageId = getFinalStage()?.id;
  const idx = state.stages.findIndex((s) => s.id === state.selectedStageId);
  const isFinal = state.selectedStageId === finalStageId;
  const maxed = state.stages.length >= MAX_STAGES;
  if (addStageBtnEl) addStageBtnEl.disabled = maxed;
  if (removeStageBtnEl) removeStageBtnEl.disabled = isFinal || state.stages.length <= 1;
  if (moveStageUpBtnEl) moveStageUpBtnEl.disabled = isFinal || idx <= 0;
  if (moveStageDownBtnEl) moveStageDownBtnEl.disabled = isFinal || idx < 0 || idx >= state.stages.length - 2;
}

function renderOverviewSummary() {
  if (overviewStageTableEl) {
    overviewStageTableEl.innerHTML = "";
    state.stages.forEach((s, idx) => {
      const isFinalStage = s.id === getFinalStage()?.id;
      const roles = s.member_ids
        .map((id) => state.members.find((m) => m.id === id))
        .filter(Boolean);
      const roleChips = roles
        .map((r) => `<span class="pill">${escapeHtml(r.alias)}</span>`)
        .join("");
      const row = document.createElement("div");
      row.className = "overview-table-row";
      row.innerHTML = `
        <div class="overview-table-head">
          <div><strong>${escapeHtml(s.name)}</strong> ${isFinalStage ? "★" : ""}</div>
          <div class="pill kind-${escapeAttr(s.kind || "responses")}">${escapeHtml(s.kind)}</div>
        </div>
        <div class="overview-stage-meta">Stage ${idx + 1} • ${escapeHtml(s.execution_mode)} • ${roles.length} role(s)</div>
        <div class="overview-chips">${roleChips || "<span class='help'>No roles assigned</span>"}</div>
        <div class="overview-stage-meta">${escapeHtml(shortPrompt(s.prompt))}</div>
      `;
      overviewStageTableEl.appendChild(row);
    });
  }

  if (overviewRoleListEl) {
    overviewRoleListEl.innerHTML = "";
    state.members.forEach((m) => {
      const isSynthesisRole = getSynthesisRoleId() === m.id;
      const item = document.createElement("div");
      item.className = "overview-role-item";
      item.innerHTML = `
        <div class="overview-table-head">
          <div><strong>${escapeHtml(m.alias)}</strong> ${isSynthesisRole ? "★" : ""}</div>
          <div class="pill">${escapeHtml(m.id)}</div>
        </div>
        <div class="overview-stage-meta">Model tool: ${escapeHtml(m.model_id)}</div>
        <div class="overview-stage-meta">${isSynthesisRole ? "Synthesis Role" : "Council Role"}</div>
      `;
      overviewRoleListEl.appendChild(item);
    });
  }
}

function renderOverviewFlow() {
  renderStageList(overviewStageListEl);
  // Larger canvas for overview.
  renderGraph(graphSvgOverviewEl, 920, 360);
}

function renderMemberManager() {
  const s = activeStage();
  if (!s || !memberManagerMetaEl) return;

  const isFinalStage = s.id === getFinalStage()?.id;
  memberManagerMetaEl.textContent = isFinalStage
    ? `${s.name} • locked to 1 role • ${s.execution_mode}`
    : `${s.name} • ${s.member_ids.length}/${MAX_MEMBERS_PER_STAGE} roles • ${s.execution_mode}`;

  const assignBtn = $("#btnAssignAll");
  const clearBtn = $("#btnClearStage");
  if (assignBtn) assignBtn.disabled = isFinalStage;
  if (clearBtn) clearBtn.disabled = isFinalStage;

  const assigned = state.members.filter((m) => s.member_ids.includes(m.id));
  const available = state.members.filter((m) => !s.member_ids.includes(m.id));
  const query = (memberSearchEl?.value || "").trim().toLowerCase();
  const matches = (m) => {
    if (!query) return true;
    return (
      m.alias.toLowerCase().includes(query) ||
      m.model_id.toLowerCase().includes(query) ||
      m.id.toLowerCase().includes(query)
    );
  };

  if (assignedListEl) {
    assignedListEl.innerHTML = "";
    if (assigned.length === 0) {
      assignedListEl.appendChild(emptyState("No roles assigned yet."));
    } else {
      assigned.forEach((m) => assignedListEl.appendChild(memberCard(m, true, s.id)));
    }
  }

  if (availableListEl) {
    availableListEl.innerHTML = "";
    const filtered = available.filter(matches);
    if (filtered.length === 0) {
      availableListEl.appendChild(emptyState(query ? "No matches for this filter." : "All roles are already assigned."));
    } else {
      filtered.forEach((m) => availableListEl.appendChild(memberCard(m, false, s.id)));
    }
  }
}

function memberCard(member, isAssigned, stageId) {
  const el = document.createElement("div");
  el.className = "member-card" + (member.id === state.selectedMemberId ? " is-active" : "");
  el.innerHTML = `
    <div>
      <div class="member-title">${escapeHtml(member.alias)} ${getSynthesisRoleId() === member.id ? "★" : ""}</div>
      <div class="member-meta">${escapeHtml(member.model_id)}</div>
    </div>
    <div>
      <button class="btn btn-ghost btn-small">${isAssigned ? "Remove" : "Add"}</button>
    </div>
  `;
  const btn = el.querySelector("button");
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleMembership(stageId, member.id);
  });
  el.addEventListener("click", () => {
    state.selectedMemberId = member.id;
    renderAll();
  });
  return el;
}

function emptyState(text) {
  const el = document.createElement("div");
  el.className = "help";
  el.textContent = text;
  return el;
}

function assignAllMembers(stageId) {
  const s = state.stages.find((x) => x.id === stageId);
  if (!s) return;
  const isFinalStage = s.id === getFinalStage()?.id;
  if (isFinalStage) {
    const first = state.members[0]?.id;
    if (first) {
      s.member_ids = [first];
      toast("Final Synthesis keeps exactly one role.");
    }
    renderAll();
    return;
  }
  const next = [];
  for (const m of state.members) {
    if (next.length >= MAX_MEMBERS_PER_STAGE) break;
    next.push(m.id);
  }
  if (state.members.length > MAX_MEMBERS_PER_STAGE) {
    toast(`Assigned first ${MAX_MEMBERS_PER_STAGE} roles (max per stage).`);
  }
  s.member_ids = next;
  renderAll();
}

function clearStageMembers(stageId) {
  const s = state.stages.find((x) => x.id === stageId);
  if (!s) return;
  if (s.id === getFinalStage()?.id) {
    toast("Final Synthesis must keep exactly one role.");
    return;
  }
  s.member_ids = [];
  renderAll();
}

function toggleMembership(stageId, memberId) {
  const s = state.stages.find((x) => x.id === stageId);
  if (!s) return;
  const isFinalStage = s.id === getFinalStage()?.id;
  const set = new Set(s.member_ids || []);
  if (set.has(memberId)) {
    if (isFinalStage) {
      toast("Final Synthesis must have exactly one role.");
      return;
    }
    set.delete(memberId);
  } else {
    if (set.size >= MAX_MEMBERS_PER_STAGE) {
      toast(`Stage '${s.name}' already has ${MAX_MEMBERS_PER_STAGE} roles (max).`);
      return;
    }
    if (isFinalStage) {
      set.clear();
    }
    set.add(memberId);
  }
  s.member_ids = Array.from(set);
  // Keep selections sane.
  if (stageId === state.selectedStageId && !s.member_ids.includes(state.selectedMemberId)) {
    state.selectedMemberId = s.member_ids[0] || state.selectedMemberId;
  }
  renderAll();
}

function addStage() {
  if (state.stages.length >= MAX_STAGES) {
    toast(`Max stages reached (${MAX_STAGES}).`);
    return;
  }
  ensureFinalStage();
  const id = `s${Date.now()}`;
  const name = `Stage ${state.stages.length + 1}`;
  const defaultMembers = state.members.slice(0, Math.min(3, state.members.length)).map((m) => m.id);
  const member_ids = defaultMembers.length ? defaultMembers : [state.members[0]?.id].filter(Boolean);
  const insertIndex = Math.max(0, state.stages.length - 1);
  state.stages.splice(insertIndex, 0, {
    id,
    name,
    kind: "responses",
    type: "ai",
    execution_mode: "parallel",
    prompt: "",
    member_ids,
  });
  state.selectedStageId = id;
  state.selectedMemberId = member_ids[0] || state.selectedMemberId;
  renderAll();
}

function removeStage() {
  if (state.stages.length <= 1) {
    toast("At least one stage is required.");
    return;
  }
  const idx = state.stages.findIndex((s) => s.id === state.selectedStageId);
  if (idx < 0) return;
  if (state.selectedStageId === getFinalStage()?.id) {
    toast("Final Synthesis stage cannot be removed.");
    return;
  }
  const removed = state.stages.splice(idx, 1);
  if (removed[0]?.id === state.selectedStageId) {
    state.selectedStageId = state.stages[Math.max(0, idx - 1)]?.id || state.stages[0].id;
  }
  renderAll();
}

function moveStage(direction) {
  const idx = state.stages.findIndex((s) => s.id === state.selectedStageId);
  if (idx < 0) return;
  if (state.selectedStageId === getFinalStage()?.id) {
    toast("Final Synthesis stage stays last.");
    return;
  }
  const next = idx + direction;
  if (next < 0 || next >= state.stages.length) return;
  if (state.stages[next]?.id === getFinalStage()?.id) {
    toast("Final Synthesis stage stays last.");
    return;
  }
  const [item] = state.stages.splice(idx, 1);
  state.stages.splice(next, 0, item);
  renderAll();
}

function addMember() {
  const id = `m${Date.now()}`;
  const alias = `Role ${state.members.length + 1}`;
  const model_id = `custom.model-${state.members.length + 1}`;
  state.members.push({ id, alias, model_id });
  ensureFinalStage();
  state.selectedMemberId = id;
  renderAll();
}

function removeMember(memberId) {
  const member = state.members.find((m) => m.id === memberId);
  if (!member) return;
  if (state.members.length <= 1) {
    toast("At least one role is required.");
    return;
  }
  state.members = state.members.filter((m) => m.id !== memberId);
  state.stages.forEach((s) => {
    s.member_ids = (s.member_ids || []).filter((id) => id !== memberId);
    if (s.member_ids.length === 0) {
      s.member_ids = [state.members[0]?.id].filter(Boolean);
    }
  });
  ensureFinalStage();
  if (!state.members.some((m) => m.id === state.selectedMemberId)) {
    state.selectedMemberId = state.members[0]?.id;
  }
  renderAll();
}

function renderInspector() {
  const s = activeStage();
  const m = activeMember();
  const isFinalStage = s?.id === getFinalStage()?.id;
  const showStageMembership = currentStep === "stages";

  inspectorStageEl.innerHTML = `
    <div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline;">
      <div style="font-weight:900;">Stage: ${escapeHtml(s.name)}</div>
      <div class="pill" style="border-color:${stageColor(s.kind,s.type)};color:rgba(243,244,246,0.92)">${escapeHtml(s.kind)}</div>
    </div>

    <div class="field">
      <div class="label">Kind</div>
      <select class="input" id="stageKind" ${isFinalStage ? "disabled" : ""}>
        ${option("responses", s.kind)}
        ${option("rankings", s.kind)}
        ${isFinalStage ? option("synthesis", s.kind) : ""}
      </select>
      <div class="help">${isFinalStage ? "Final stage is locked to Synthesis." : "Defines what the UI expects this stage to produce."}</div>
    </div>

    <div class="field">
      <div class="label">Execution Mode</div>
      <select class="input" id="stageExec" ${isFinalStage ? "disabled" : ""}>
        ${option("parallel", s.execution_mode)}
        ${option("sequential", s.execution_mode)}
      </select>
    </div>

    <div class="field">
      <div class="label">Stage Roles (${s.member_ids.length}/${MAX_MEMBERS_PER_STAGE})</div>
      <div class="chips" id="stageMembersChips"></div>
      <div class="help">${isFinalStage ? "Final Synthesis requires exactly one role." : `Click a chip to include/exclude a role. Max ${MAX_MEMBERS_PER_STAGE} per stage.`}</div>
    </div>

    <div class="field">
      <div class="label">Prompt Template</div>
      <textarea class="input" id="stagePrompt" rows="7">${escapeHtml(s.prompt || "")}</textarea>
      <div class="help">Placeholders: <span style="font-family:var(--mono)">{question}</span>, <span style="font-family:var(--mono)">{responses}</span>, <span style="font-family:var(--mono)">{stage1}</span>, <span style="font-family:var(--mono)">{stage2}</span></div>
    </div>

    <div class="field">
      <button class="btn btn-secondary" id="btnOpenPreviewInline" type="button">Open Prompt Preview</button>
    </div>
  `;

  inspectorMemberEl.innerHTML = `
    <div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline;">
      <div style="font-weight:900;">Member Role: ${escapeHtml(m.alias)}</div>
      <div class="pill">${escapeHtml(m.model_id)}</div>
    </div>
    <div class="field">
      <div class="label">Role / Seat Name</div>
      <input class="input" id="memberAlias" value="${escapeAttr(m.alias)}" />
    </div>
    <div class="field">
      <div class="label">Assigned Model (tool)</div>
      <input class="input" id="memberModel" value="${escapeAttr(m.model_id)}" />
      <div class="help">Models are tools. Changing a model does not change the member role.</div>
    </div>
    ${showStageMembership ? `
      <div class="field">
        <div class="label">Participates In Selected Stage?</div>
        <div class="chips">
          <button class="chip ${s.member_ids.includes(m.id) ? "is-active" : ""}" id="btnToggleMember">
            ${s.member_ids.includes(m.id) ? "Included" : "Excluded"}
          </button>
        </div>
        <div class="help">This is the fastest way to answer: “Who does what, where?”</div>
      </div>
    ` : ""}
    <div class="field">
      <div class="chips">
        <button class="chip" id="btnRemoveMember">Remove Member</button>
      </div>
      <div class="help">Role assignments are handled in the Stages step.</div>
    </div>
  `;

  if (!isFinalStage) {
    $("#stageKind").addEventListener("change", (e) => {
      s.kind = e.target.value;
      renderAll();
    });
    $("#stageExec").addEventListener("change", (e) => {
      s.execution_mode = e.target.value;
      renderAll();
    });
  }
  const chips = $("#stageMembersChips");
  if (chips) {
    chips.innerHTML = "";
    state.members.forEach((member) => {
      const included = s.member_ids.includes(member.id);
      const chip = document.createElement("button");
      chip.className = "chip" + (included ? " is-active" : "");
      chip.textContent = member.alias;
      chip.addEventListener("click", () => toggleMembership(s.id, member.id));
      chips.appendChild(chip);
    });
  }
  $("#stagePrompt").addEventListener("input", (e) => {
    s.prompt = e.target.value;
    // Avoid re-rendering everything on every keystroke; just update lint + diff in-place.
    renderLint();
    renderDiff();
  });
  $("#btnOpenPreviewInline").addEventListener("click", () => {
    openPreview();
  });
  if (showStageMembership) {
    $("#btnToggleMember").addEventListener("click", () => {
      toggleMembership(s.id, m.id);
    });
  }
  $("#memberAlias").addEventListener("input", (e) => {
    m.alias = e.target.value;
    renderStageList();
    renderMatrix();
    renderStagesView();
    renderOverviewSummary();
    renderRolesView();
    renderRoster();
  });
  $("#memberModel").addEventListener("input", (e) => {
    m.model_id = e.target.value;
    renderRoster();
    renderStagesView();
    renderOverviewSummary();
    renderRolesView();
  });
  $("#btnRemoveMember").addEventListener("click", () => {
    removeMember(m.id);
  });
}

function option(value, current) {
  const sel = value === current ? "selected" : "";
  return `<option value="${escapeAttr(value)}" ${sel}>${escapeHtml(value)}</option>`;
}

function renderLint() {
  const issues = lint(state);
  if (lintListEl) lintListEl.innerHTML = "";
  if (lintListOverviewEl) {
    lintListOverviewEl.innerHTML = "";
  }
  if (issues.length === 0) {
    const item = lintItem("ok", "No issues detected", "This pipeline passes the basic static checks.");
    if (lintListEl) lintListEl.appendChild(item);
    if (lintListOverviewEl) lintListOverviewEl.appendChild(item.cloneNode(true));
    return;
  }
  for (const it of issues) {
    const node = lintItem(it.level, it.title, it.hint);
    if (lintListEl) lintListEl.appendChild(node);
    if (lintListOverviewEl) lintListOverviewEl.appendChild(node.cloneNode(true));
  }
}

function lintItem(level, title, hint) {
  const el = document.createElement("div");
  el.className = `lint-item is-${level}`;
  el.innerHTML = `<strong>${escapeHtml(title)}</strong><div class="hint">${escapeHtml(hint)}</div>`;
  return el;
}

function lint(st) {
  const out = [];
  const stageById = new Map(st.stages.map((s) => [s.id, s]));
  const memberIds = new Set(st.members.map((m) => m.id));

  for (const s of st.stages) {
    if (!s.name || !String(s.name).trim()) {
      out.push({ level: "error", title: "Stage with empty name", hint: "Name stages so the matrix and graph are scannable." });
    }
    if (!s.member_ids || s.member_ids.length === 0) {
      out.push({ level: "error", title: `Stage '${s.name}' has 0 roles`, hint: "Add at least one role, or remove the stage." });
    }
    if ((s.member_ids || []).length > MAX_MEMBERS_PER_STAGE) {
      out.push({ level: "error", title: `Stage '${s.name}' exceeds ${MAX_MEMBERS_PER_STAGE} roles`, hint: "Reduce roles to keep execution practical." });
    }
    if ((s.member_ids || []).some((id) => !memberIds.has(id))) {
      out.push({ level: "error", title: `Stage '${s.name}' references unknown roles`, hint: "This would fail backend validation." });
    }
    if (s.kind === "rankings") {
      if (!String(s.prompt || "").includes("{responses}")) {
        out.push({
          level: "warn",
          title: `Rankings stage '${s.name}' missing {responses}`,
          hint: "Without {responses}, reviewers won't see prior outputs.",
        });
      }
    }
    if (s.kind === "synthesis") {
      if ((s.member_ids || []).length !== 1) {
        out.push({ level: "warn", title: `Synthesis stage '${s.name}' has ${s.member_ids.length} roles`, hint: "Usually synthesis is single-author for consistency." });
      }
      if (!String(s.prompt || "").includes("{stage1}")) {
        out.push({ level: "warn", title: `Synthesis stage '${s.name}' missing {stage1}`, hint: "Synthesis role may not see individual responses." });
      }
      if (!String(s.prompt || "").includes("{stage2}")) {
        out.push({ level: "warn", title: `Synthesis stage '${s.name}' missing {stage2}`, hint: "Synthesis role may not see peer rankings." });
      }
    }
  }

  // Simple dependency check: synthesis requires a responses and rankings stage before it.
  const synthesisIndex = st.stages.findIndex((s) => s.kind === "synthesis");
  if (synthesisIndex >= 0) {
    const before = st.stages.slice(0, synthesisIndex);
    const hasResponses = before.some((s) => s.kind === "responses");
    const hasRankings = before.some((s) => s.kind === "rankings");
    if (!hasResponses) out.push({ level: "warn", title: "No responses stage before synthesis", hint: "Synthesis will have little to synthesize." });
    if (!hasRankings) out.push({ level: "warn", title: "No rankings stage before synthesis", hint: "Synthesis will miss comparative signal." });
  }

  if (st.stages.length > MAX_STAGES) {
    out.push({ level: "error", title: `Too many stages (${st.stages.length})`, hint: `Max is ${MAX_STAGES}.` });
  }

  // Final synthesis stage validation.
  const finalStage = st.stages[st.stages.length - 1];
  if (!finalStage || finalStage.kind !== "synthesis") {
    out.push({ level: "error", title: "Final stage must be Synthesis", hint: "The last stage is required and locked to synthesis." });
  } else if ((finalStage.member_ids || []).length !== 1) {
    out.push({ level: "error", title: "Final Synthesis must have exactly one role", hint: "Assign a single role to the final stage." });
  }

  return out;
}

function renderGraph(svgEl, W = 520, H = 300) {
  if (!svgEl) return;
  svgEl.innerHTML = "";

  // Layout nodes horizontally with subtle vertical offsets by kind.
  const paddingX = 34;
  const spacing = (W - paddingX * 2) / Math.max(1, state.stages.length - 1);
  const pos = {};

  state.stages.forEach((s, idx) => {
    const x = paddingX + idx * spacing;
    const y =
      s.type === "human" ? 220 :
      s.kind === "rankings" ? 170 :
      s.kind === "synthesis" ? 110 : 140;
    pos[s.id] = { x, y };
  });

  // Edges.
  for (let i = 0; i < state.stages.length - 1; i++) {
    const a = state.stages[i];
    const b = state.stages[i + 1];
    const pa = pos[a.id];
    const pb = pos[b.id];
    svgEl.appendChild(svgPath(pa.x + 34, pa.y, pb.x - 34, pb.y));
  }

  // Nodes.
  for (const s of state.stages) {
    const p = pos[s.id];
    const isActive = s.id === state.selectedStageId;
    const fill = stageColor(s.kind, s.type);
    svgEl.appendChild(svgNode(p.x, p.y, s.name, s.kind, s.type, fill, isActive, () => {
      state.selectedStageId = s.id;
      if (!s.member_ids.includes(state.selectedMemberId)) {
        state.selectedMemberId = s.member_ids[0] || state.selectedMemberId;
      }
      renderAll();
    }));
  }
}

function svgPath(x1, y1, x2, y2) {
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
  const mx = (x1 + x2) / 2;
  p.setAttribute("d", `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`);
  p.setAttribute("fill", "none");
  p.setAttribute("stroke", "rgba(255,255,255,0.16)");
  p.setAttribute("stroke-width", "2");
  return p;
}

function svgNode(x, y, name, kind, type, fill, isActive, onClick) {
  const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
  g.setAttribute("transform", `translate(${x - 58}, ${y - 26})`);
  g.style.cursor = "pointer";

  const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  rect.setAttribute("width", "116");
  rect.setAttribute("height", "52");
  rect.setAttribute("rx", "14");
  rect.setAttribute("fill", "rgba(18,20,23,0.92)");
  rect.setAttribute("stroke", isActive ? "rgba(62,207,142,0.45)" : "rgba(255,255,255,0.14)");
  rect.setAttribute("stroke-width", isActive ? "2" : "1.5");
  g.appendChild(rect);

  const bar = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  bar.setAttribute("x", "10");
  bar.setAttribute("y", "10");
  bar.setAttribute("width", "10");
  bar.setAttribute("height", "32");
  bar.setAttribute("rx", "6");
  bar.setAttribute("fill", fill);
  g.appendChild(bar);

  const t1 = document.createElementNS("http://www.w3.org/2000/svg", "text");
  t1.setAttribute("x", "28");
  t1.setAttribute("y", "28");
  t1.setAttribute("fill", "rgba(243,244,246,0.96)");
  t1.setAttribute("font-size", "12");
  t1.setAttribute("font-weight", "800");
  t1.textContent = trim(name, 16);
  g.appendChild(t1);

  const t2 = document.createElementNS("http://www.w3.org/2000/svg", "text");
  t2.setAttribute("x", "28");
  t2.setAttribute("y", "42");
  t2.setAttribute("fill", "rgba(161,161,170,0.92)");
  t2.setAttribute("font-size", "11");
  t2.textContent = `${kind}${type === "human" ? " • human" : ""}`;
  g.appendChild(t2);

  g.addEventListener("click", onClick);
  return g;
}

function trim(s, n) {
  const t = String(s || "");
  return t.length > n ? t.slice(0, n - 1) + "…" : t;
}

function renderDiff() {
  // This is the conceptual payload sent to backend /api/settings/council.
  const chairmanId = getSynthesisRoleId() || state.members[0]?.id || "";
  const payload = {
    version: 2,
    members: state.members.map((m) => ({
      id: m.id,
      alias: m.alias,
      model_id: m.model_id,
      system_prompt: "",
    })),
    chairman_id: chairmanId,
    chairman_label: "Chairman",
    title_model_id: state.members[0]?.model_id || "",
    use_system_prompt_stage2: true,
    use_system_prompt_stage3: true,
    speaker_context_level: state.speaker_context_level,
    stages: state.stages.map((s) => ({
      id: s.id,
      name: s.name,
      kind: s.kind,
      type: s.type,
      prompt: s.prompt,
      execution_mode: s.execution_mode,
      member_ids: s.member_ids,
    })),
  };
  diffBoxEl.textContent = JSON.stringify(payload, null, 2);
}

function renderPreview() {
  const s = activeStage();
  const m = activeMember();
  const ctx = fakePriorContext();
  const values = {
    question: state.question,
    responses: ctx.responses,
    stage1: ctx.stage1,
    stage2: ctx.stage2,
  };
  const rendered = applyTemplate(s.prompt || "", values);
  previewBoxEl.textContent = rendered || "(empty prompt)";

  previewControlsEl.innerHTML = `
    <button class="btn btn-secondary" id="btnPickQuestion">Change Sample Question</button>
    <button class="btn btn-secondary" id="btnCopyPreview">Copy Rendered Prompt</button>
    <div class="pill">Stage: ${escapeHtml(s.name)}</div>
    <div class="pill">Role: ${escapeHtml(m.alias)}</div>
  `;
  $("#btnPickQuestion").addEventListener("click", () => {
    const next = window.prompt("Sample question used for templating:", state.question);
    if (next !== null) state.question = next;
    renderPreview();
    renderDiff();
    toast("Updated sample question");
  });
  $("#btnCopyPreview").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(previewBoxEl.textContent || "");
      toast("Copied rendered prompt");
    } catch {
      toast("Copy failed (browser permissions)");
    }
  });
}

function renderRoster() {
  rosterBlockEl.innerHTML = `
    <div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline;">
      <div style="font-weight:900;">Roles</div>
      <button class="btn btn-secondary" id="btnAddMember" type="button">Add Member</button>
    </div>
    <div class="roster-list" id="rosterList"></div>
    <div class="help">Click a role to inspect.</div>
  `;
  const list = $("#rosterList");
  state.members.forEach((m) => {
    const item = document.createElement("div");
    item.className = "roster-item" + (m.id === state.selectedMemberId ? " is-active" : "");
    item.innerHTML = `
      <div>
        <div><strong>${escapeHtml(m.alias)}</strong> ${getSynthesisRoleId() === m.id ? "★" : ""}</div>
        <div class="roster-meta">${escapeHtml(m.model_id)}</div>
      </div>
      <div class="pill">${escapeHtml(m.id)}</div>
    `;
    item.addEventListener("click", () => {
      state.selectedMemberId = m.id;
      renderAll();
    });
    list.appendChild(item);
  });
  $("#btnAddMember").addEventListener("click", addMember);
}

function closeOverlay() {
  overlayMode = null;
  panelPreviewEl.classList.add("is-hidden");
  panelDiffEl.classList.add("is-hidden");
}

function openPreview() {
  overlayMode = "preview";
  panelPreviewEl.classList.remove("is-hidden");
  panelDiffEl.classList.add("is-hidden");
  if (panelLeftEl) panelLeftEl.classList.add("is-hidden");
  panelCenterEl.classList.add("is-hidden");
  panelRightEl.classList.add("is-hidden");
  layoutEl.classList.remove("is-two");
  layoutEl.classList.add("is-single");
  renderPreview();
}

function openDiff() {
  overlayMode = "diff";
  panelDiffEl.classList.remove("is-hidden");
  panelPreviewEl.classList.add("is-hidden");
  if (panelLeftEl) panelLeftEl.classList.add("is-hidden");
  panelCenterEl.classList.add("is-hidden");
  panelRightEl.classList.add("is-hidden");
  layoutEl.classList.remove("is-two");
  layoutEl.classList.add("is-single");
  renderDiff();
}

function activateStep(step) {
  closeOverlay();
  currentStep = step;

  for (const b of document.querySelectorAll(".step")) {
    const active = b.dataset.step === step;
    b.classList.toggle("is-active", active);
    b.setAttribute("aria-selected", active ? "true" : "false");
  }
  const idx = STEPS.indexOf(step);
  if (backBtnEl) backBtnEl.disabled = idx <= 0;
  if (nextBtnEl) nextBtnEl.disabled = idx >= STEPS.length - 1;

  const isRoles = step === "roles";
  const isStages = step === "stages";
  const isOverview = step === "overview";

  // Main layout panels
  if (panelLeftEl) panelLeftEl.classList.toggle("is-hidden", !isStages);
  panelRightEl.classList.toggle("is-hidden", !isRoles && !isStages);
  panelCenterEl.classList.remove("is-hidden");

  // Center subviews
  rolesViewEl.classList.toggle("is-hidden", !isRoles);
  stagesViewEl.classList.toggle("is-hidden", !isStages);
  overviewViewEl.classList.toggle("is-hidden", !isOverview);

  if (pipelineGraphEl) pipelineGraphEl.classList.toggle("is-hidden", true);
  if (pipelineLintEl) pipelineLintEl.classList.toggle("is-hidden", true);

  // Adjust layout grid
  layoutEl.classList.remove("is-single", "is-two");
  if (isOverview) {
    layoutEl.classList.add("is-single");
  } else if (isRoles) {
    layoutEl.classList.add("is-two");
  }

  // Inspector blocks
  if (inspectorStageEl) inspectorStageEl.classList.toggle("is-hidden", !isStages);
  if (inspectorMemberEl) inspectorMemberEl.classList.toggle("is-hidden", !isRoles);
  if (rosterBlockEl) rosterBlockEl.classList.toggle("is-hidden", true);
  if (architectEl) architectEl.classList.toggle("is-hidden", true);

  if (isRoles) {
    centerTitleEl.textContent = "Roles";
    centerMetaEl.textContent = "Define council roles and assign models as tools.";
    renderRolesView();
  }
  if (isStages) {
    centerTitleEl.textContent = "Stages";
    centerMetaEl.textContent = "Assign roles to stages and configure prompts.";
    renderStagesView();
  }
  if (isOverview) {
    centerTitleEl.textContent = "Overview";
    centerMetaEl.textContent = "Review the full council configuration before running.";
    renderOverviewSummary();
    renderOverviewFlow();
  }
}

function bindStepper() {
  for (const b of document.querySelectorAll(".step")) {
    b.addEventListener("click", () => activateStep(b.dataset.step));
  }
}

function bindActions() {
  $("#btnReset").addEventListener("click", () => {
    state = DEFAULT_STATE();
    renderAll();
    activateStep("roles");
    toast("Reset prototype state");
  });
  $("#btnExport").addEventListener("click", async () => {
    renderDiff();
    try {
      await navigator.clipboard.writeText(diffBoxEl.textContent || "");
      toast("Copied settings JSON to clipboard");
    } catch {
      toast("Copy failed (browser permissions)");
    }
    openDiff();
  });
  if (backBtnEl) {
    backBtnEl.addEventListener("click", () => {
      const idx = Math.max(0, STEPS.indexOf(currentStep) - 1);
      activateStep(STEPS[idx]);
    });
  }
  if (nextBtnEl) {
    nextBtnEl.addEventListener("click", () => {
      const idx = Math.min(STEPS.length - 1, STEPS.indexOf(currentStep) + 1);
      activateStep(STEPS[idx]);
    });
  }
  if (addRoleBtnEl) {
    addRoleBtnEl.addEventListener("click", addMember);
  }

  $("#btnAddStage").addEventListener("click", addStage);
  $("#btnRemoveStage").addEventListener("click", removeStage);
  $("#btnMoveStageUp").addEventListener("click", () => moveStage(-1));
  $("#btnMoveStageDown").addEventListener("click", () => moveStage(1));

  if ($("#btnAssignAll")) {
    $("#btnAssignAll").addEventListener("click", () => assignAllMembers(activeStage().id));
  }
  if ($("#btnClearStage")) {
    $("#btnClearStage").addEventListener("click", () => clearStageMembers(activeStage().id));
  }
  if (memberSearchEl) {
    memberSearchEl.addEventListener("input", renderMemberManager);
  }

  const previewBtn = $("#btnOpenPreview");
  if (previewBtn) previewBtn.addEventListener("click", openPreview);
  const diffBtn = $("#btnOpenDiff");
  if (diffBtn) diffBtn.addEventListener("click", openDiff);

  $("#btnPropose").addEventListener("click", () => {
    const input = ($("#architectInput").value || "").trim();
    const patch = proposePatch(input);
    $("#architectOutput").textContent = JSON.stringify(patch, null, 2);
    toast("Generated patch preview (mock)");
  });
}

function proposePatch(text) {
  // This is intentionally dumb; in the real app this is where you'd call Bedrock.
  if (!text) {
    return { note: "Describe what you want changed. This prototype doesn't call an LLM." };
  }
  const wantsDebate = /debate|critique|review/i.test(text);
  if (!wantsDebate) {
    return { note: "Mock: no recognized intent. Try words like 'debate', 'critique', 'add stage'." };
  }
  return {
    op: "insert_stage",
    after_stage: "Peer Rankings",
    stage: {
      id: "s2b",
      name: "Focused Critique",
      kind: "responses",
      type: "ai",
      execution_mode: "sequential",
      member_ids: ["m1", "m3"],
      prompt:
        "Question: {question}\n\nPrior outputs:\n{responses}\n\nCritique the strongest and weakest parts. Then propose an improved combined answer.",
    },
    safety: [
      "diff-first apply",
      "validate stage has members",
      "ensure synthesis still single-member",
    ],
  };
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
function escapeAttr(s) { return escapeHtml(s); }

function cellEl(cls, text) {
  const el = document.createElement("div");
  el.className = cls;
  el.textContent = text;
  return el;
}

function renderAll() {
  ensureFinalStage();
  // Ensure selected ids still exist.
  if (!state.stages.some((s) => s.id === state.selectedStageId)) state.selectedStageId = state.stages[0]?.id;
  if (!state.members.some((m) => m.id === state.selectedMemberId)) state.selectedMemberId = state.members[0]?.id;

  renderStageList();
  renderOverviewFlow();
  renderStagesView();
  renderOverviewSummary();
  renderRolesView();
  renderMatrix();
  renderLint();
  renderInspector();
  renderRoster();
  renderDiff();
}

bindStepper();
bindActions();
activateStep("roles");
renderAll();

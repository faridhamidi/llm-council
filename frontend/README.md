# LLM Council Frontend

The React/Vite frontend for the LLM Council application.

## Overview

This interface allows users to:
- Submit queries to the LLM Council.
- View real-time streaming progress of deliberation stages (parallel responses, rankings, synthesis).
- Configure council members, system prompts, and stage pipelines.
- Manage conversation history.

## Structure

- **`App.jsx`**: Main application state, auth checks (PIN), and router.
- **`components/ChatInterface.jsx`**: The core chat view. Handles message composition, history rendering, and "Stage Builder" interactions.
- **`components/Sidebar.jsx`**: Navigation sidebar for history and settings.
- **`components/StageBuilder.jsx`**: Drag-and-drop UI for configuring the council pipeline.
- **`components/Stage1.jsx` / `Stage2.jsx` / `Stage3.jsx`**: Specialized views for different deliberation outputs.
- **`api.js`**: Centralized API client interacting with the Python backend (port 8001).

## Development

1. **Install Dependencies**:
   ```bash
   npm install
   ```

2. **Run Dev Server**:
   ```bash
   npm run dev
   ```

3. **Build**:
   ```bash
   npm run build
   ```

## Key Technologies

- **Vite**: Fast build tool and dev server.
- **React**: Component library.
- **TailwindCSS**: Utility-first styling (extended by `DESIGN_SYSTEM.md` principles).
- **React Markdown**: Rendering LLM responses.
- **Lucide React**: Iconography.

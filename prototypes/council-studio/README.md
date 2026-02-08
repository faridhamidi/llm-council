# Council Studio Prototype

This is a standalone, clickable prototype to visualize the "externalization model":

- Pipeline shape (graph + stage cards)
- Membership matrix (who participates where)
- Inspector (edit stage kind/execution/prompt)
- Prompt preview (rendered template)
- Lint panel (static checks)

## Open

1. Open `prototypes/council-studio/index.html` in your browser.

If your browser blocks some interactions (clipboard), serve it locally:

```bash
cd prototypes/council-studio
python3 -m http.server 7333
```

Then open `http://localhost:7333`.

